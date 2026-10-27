"""服务端选择卡生成/恢复；确认在现有消息事务中调用，不另开写入事务。"""

import json
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.choices import (
    AssignInfo,
    ChoiceForm,
    ChoiceKind,
    ChoiceOption,
    ChoiceSelection,
    FormGroupInput,
    answered_form,
    build_form,
    form_patch,
    pace_options,
    pace_patch,
    trip_ask_form,
)
from backend.domain.choices import (
    ChoiceCard as ChoiceCard,
)
from backend.domain.execution import RunContext
from backend.domain.hotel_recovery import HotelSearchDiagnostics
from backend.domain.memory import LONG_TERM_ELIGIBLE
from backend.domain.memory_merge import card_candidates
from backend.domain.travel_request import RequestPatch, TravelRequest, pace_of
from backend.persistence import memory, runs, sessions
from backend.persistence import travel as requests
from backend.persistence.models import ChoiceCardRow, MemoryFactRow
from backend.services import conversation
from backend.services.common import ServiceError, transaction
from backend.services.memory import MemoryService, erase, has_draft
from backend.services.travel import TravelService, request_from_row, require_revision

# 记忆合并确认卡(docs/plans/2026-10-19-memory-flow.md)：草稿暂存之后，由tools.travel的暂存分支调用
# ChoiceService.merge_memory_cards，把本会话新增/变更的可长期偏好合成“一组”memory_confirm卡
# (默认记住，页面一次确认，沿用ChoiceSelection.also)。run后异步抽取的逐条memory_confirm路径不变。
MEMORY_MERGE_EXTENSION_POINT = "after_draft_staged"
# 已确认的记忆键中，可替代合并选择卡里 节奏/交通/起床/晚上结束 四组的键。
MEMORY_ASK_KEYS = frozenset(LONG_TERM_ELIGIBLE)
# 发卡的前提只要城市/日期/人数/房间；儿童年龄未知由卡里的“同行儿童”组来问，不能挡住发卡。
CORE_FIELDS = ("city", "start_date", "end_date", "adults", "rooms")
ASK_QUESTION = "请一次确认以下信息，再继续"


class ChoiceService:
    def __init__(self, travel: TravelService) -> None:
        self.travel = travel

    async def ensure_trip_ask(self, context: RunContext) -> tuple[ChoiceCard | None, bool]:
        async with transaction(self.travel.database) as db:
            return await self.ensure_trip_ask_in_transaction(db, context)

    async def ensure_trip_ask_in_transaction(
        self, db: AsyncSession, context: RunContext
    ) -> tuple[ChoiceCard | None, bool]:
        """核心条件齐全后，把仍未定的行程信息合并成一张卡；返回(未答的卡, 是否本次新建)。

        每个问题至多问一次：已答过的组不再出现；同一未答卡按当前条件复用；条件变化致过期则按剩余项重发。
        """
        row = await requests.owned_request(db, context)
        if row is None:
            raise ServiceError(404, "blocked", "会话不存在")
        request = request_from_row(row)
        if not conversation.stored_state(row).pending_tasks:
            return None, False  # 没有已授权的待办：不发卡，也不要求执行记录(纯查询/评测流程)
        cards = list(
            await db.scalars(
                select(ChoiceCardRow)
                .where(
                    ChoiceCardRow.session_id == context.session_id,
                    ChoiceCardRow.kind == "form",
                    ChoiceCardRow.content["purpose"].astext == "trip_ask",
                )
                .order_by(ChoiceCardRow.created_at.desc())
            )
        )
        asked = {
            group.key
            for card in cards
            if card.answered_option_id is not None
            for group in ChoiceForm.model_validate(card.content["form"]).groups
        }
        open_card = next(
            (c for c in cards if c.answered_option_id is None and not c.content.get("superseded")),
            None,
        )
        form: ChoiceForm | None = None
        if all(getattr(request, field) is not None for field in CORE_FIELDS):
            known = frozenset(
                fact.key
                for fact in await memory.active(db, context.user_id, context.session_id)
                if fact.key in MEMORY_ASK_KEYS
            )
            form = trip_ask_form(request, conversation.stored_state(row).pending_tasks, known)
            if form is not None:
                remaining = tuple(g for g in form.groups if g.key not in asked)
                form = ChoiceForm(purpose="trip_ask", groups=remaining) if remaining else None
        if form is None:
            if open_card is not None:  # 条件已齐全/已知，旧的未答卡不应继续挡路
                open_card.content = {**open_card.content, "superseded": True}
            return None, False
        if open_card is not None:
            current = card_from_row(open_card, request.revision)
            if not current.stale and current.form == form:
                return current, False
        await conversation.require_current_run(db, context)
        await self.supersede_forms(db, context)
        card = ChoiceCard(
            kind="form",
            session_id=context.session_id,
            source_run_id=context.run_id,
            expected_revision=request.revision,
            question=ASK_QUESTION,
            options=(ChoiceOption(option_id="confirm", label="确认并继续", value="confirm"),),
            form=form,
        )
        db.add(
            ChoiceCardRow(
                id=card.choice_id,
                session_id=card.session_id,
                source_run_id=card.source_run_id,
                kind=card.kind,
                expected_revision=card.expected_revision,
                created_at=card.created_at,
                content={
                    "question": card.question,
                    "options": [option.model_dump(mode="json") for option in card.options],
                    "form": form.model_dump(mode="json"),
                    "purpose": "trip_ask",
                },
            )
        )
        await db.flush()
        return card, True

    async def merge_memory_cards(self, context: RunContext) -> list[dict[str, object]]:
        async with transaction(self.travel.database) as db:
            return await self.merge_memory_cards_in_transaction(db, context)

    async def merge_memory_cards_in_transaction(
        self, db: AsyncSession, context: RunContext
    ) -> list[dict[str, object]]:
        """草稿暂存之后，把本会话新增/变更的可长期偏好合成一组确认卡(默认“记住”)。

        证据只有两类，都由服务端核对：用户在合并选择卡上已提交的答案，以及用户原话经
        异步抽取校验后暂缓的提议。模型不构造这批卡，也不能确认。无草稿不发；同一轮至多一组；
        已存在且不变/用户已拒绝/本卡答案已评估过的偏好不再提议。
        """
        row = await requests.owned_request(db, context)
        if row is None or not await has_draft(db, context):
            return []
        await conversation.require_current_run(db, context)
        run = await runs.owned(db, context.user_id, context.run_id)
        user = await sessions.get_user(db, context.user_id, lock=True)
        assert run and user
        if user.memory_forgotten_at is not None and run.created_at < user.memory_forgotten_at:
            return []
        request = request_from_row(row)
        service = MemoryService(self.travel.database)
        issued = list(
            await db.scalars(
                select(ChoiceCardRow).where(
                    ChoiceCardRow.session_id == context.session_id,
                    ChoiceCardRow.kind == "memory_confirm",
                    ChoiceCardRow.content["merged_run_id"].astext == str(context.run_id),
                )
            )
        )
        if issued:
            return await service.views(db, context, issued, request.revision)
        active = await memory.active(db, context.user_id, context.session_id)
        eligible = MemoryFactRow.key.in_(LONG_TERM_ELIGIBLE)
        rejected = list(
            await db.scalars(
                select(MemoryFactRow).where(
                    MemoryFactRow.user_id == context.user_id,
                    MemoryFactRow.status == "rejected",
                    eligible,
                )
            )
        )
        pending = list(
            await db.scalars(
                select(MemoryFactRow).where(
                    MemoryFactRow.user_id == context.user_id,
                    MemoryFactRow.session_id == context.session_id,
                    MemoryFactRow.status == "proposed",
                    eligible,
                )
            )
        )
        deferred: dict[str, tuple[MemoryFactRow, ChoiceCardRow]] = {}
        shown: set[str] = set()  # 已有展示中的待确认卡的键：不重复提议
        for fact in pending:
            hidden = await service.deferred_card(db, context, fact)
            if hidden is None:
                shown.add(fact.key)
            else:
                deferred[fact.key] = (fact, hidden)

        def settled(key: str, value: object) -> bool:
            return any(r.key == key and r.value == value for r in (*active, *rejected))

        def long_term(key: str) -> list[MemoryFactRow]:
            return [r for r in active if r.key == key and r.scope == "long_term"]

        built: dict[str, tuple[MemoryFactRow, ChoiceCardRow]] = {}
        for key, (fact, hidden) in deferred.items():
            target_id = hidden.content.get("target_fact_id")
            current = long_term(key)
            if key in shown or settled(key, fact.value):
                erase(fact)  # 已不变/已被拒绝：不打扰用户
            elif target_id and not any(str(r.id) == target_id for r in current):
                erase(fact)  # 要更新的目标已变化
            else:
                if not target_id and current:  # 暂缓期间出现了已确认值：改为更新它
                    hidden.content = {
                        **hidden.content,
                        "operation": "UPDATE",
                        "target_fact_id": str(current[0].id),
                    }
                built[key] = (fact, hidden)
        answered = await db.scalars(
            select(ChoiceCardRow)
            .where(
                ChoiceCardRow.session_id == context.session_id,
                ChoiceCardRow.kind == "form",
                ChoiceCardRow.content["purpose"].astext == "trip_ask",
                ChoiceCardRow.answered_option_id.is_not(None),
            )
            .order_by(ChoiceCardRow.created_at.desc())
        )
        for source in answered:
            form = ChoiceForm.model_validate(source.content["form"])
            offered = set(cast(list[str], source.content.get("memory_offered") or []))
            for candidate in card_candidates(form, request):
                if candidate.key in offered:
                    continue  # 这张卡的这个键评估过了：用户删除/拒绝后不反复提议
                offered.add(candidate.key)
                source.content = {**source.content, "memory_offered": sorted(offered)}
                if candidate.key in built or candidate.key in shown:
                    continue
                if settled(candidate.key, candidate.value):
                    continue
                current = long_term(candidate.key)
                fact = MemoryFactRow(
                    user_id=context.user_id,
                    key=candidate.key,
                    value=candidate.value,
                    scope="long_term",
                    session_id=context.session_id,
                    status="proposed",
                    source="user_utterance",
                    source_run_id=source.answered_run_id or context.run_id,
                    evidence_quote=candidate.quote,
                    ordinal=0,
                )
                db.add(fact)
                await db.flush()
                built[candidate.key] = (
                    fact,
                    service.add_card(
                        db,
                        context,
                        fact,
                        "UPDATE" if current else "ADD",
                        current[0].id if current else None,
                        request.revision,
                        deferred=True,
                    ),
                )
        rows: list[ChoiceCardRow] = []
        for key in LONG_TERM_ELIGIBLE:
            if key in built:
                card_row = built[key][1]
                card_row.content = {
                    **{k: v for k, v in card_row.content.items() if k != "deferred"},
                    "merged_run_id": str(context.run_id),
                    "default_option_id": "remember",
                }
                rows.append(card_row)
        await db.flush()
        return await service.views(db, context, rows, request.revision) if rows else []

    async def create_assign_card(
        self,
        db: AsyncSession,
        context: RunContext,
        revision: int,
        info: AssignInfo,
        extra: dict[str, object],
    ) -> ChoiceCard:
        """聊天里贴的酒店归段确认卡；同会话同时只保留一张未答的。"""
        for old in await open_cards(db, context, "hotel_assign"):
            old.content = {**old.content, "superseded": True}
        options = (
            (
                ChoiceOption(option_id="deny", label="填写城市", value="deny"),
                ChoiceOption(option_id="dismiss", label="先不选这家", value="dismiss"),
            )
            if info.needs_city
            else (
                ChoiceOption(option_id="confirm", label="确认", value="confirm"),
                ChoiceOption(option_id="deny", label="否", value="deny"),
            )
        )
        card = ChoiceCard(
            kind="hotel_assign",
            session_id=context.session_id,
            source_run_id=context.run_id,
            expected_revision=revision,
            question=(
                f"没能判断「{info.hotel_name}」属于哪个城市的住宿段，请告诉我是哪个城市"
                if info.needs_city
                else f"因为你没说，已自动归到{info.city}的住宿段，可以吗？"
            ),
            options=options,
            assign=info,
        )
        db.add(
            ChoiceCardRow(
                id=card.choice_id,
                session_id=card.session_id,
                source_run_id=card.source_run_id,
                kind=card.kind,
                expected_revision=card.expected_revision,
                created_at=card.created_at,
                content={
                    "question": card.question,
                    "options": [option.model_dump(mode="json") for option in options],
                    "assign": info.model_dump(mode="json"),
                    **extra,
                },
            )
        )
        await db.flush()
        return card

    async def create(
        self,
        context: RunContext,
        kind: ChoiceKind,
        revision: int,
        groups: tuple[FormGroupInput, ...] | None = None,
    ) -> ChoiceCard:
        async with transaction(self.travel.database) as db:
            return await self.create_in_transaction(db, context, kind, revision, groups)

    async def create_in_transaction(
        self,
        db: AsyncSession,
        context: RunContext,
        kind: ChoiceKind,
        revision: int,
        groups: tuple[FormGroupInput, ...] | None = None,
    ) -> ChoiceCard:
        row = await requests.owned_request(db, context)
        if row is None:
            raise ServiceError(404, "blocked", "会话不存在")
        request = request_from_row(row)
        require_revision(request, revision)
        await conversation.require_current_run(db, context)
        shown = build_form(request, groups) if groups else None
        existing = await db.scalars(
            select(ChoiceCardRow)
            .where(
                ChoiceCardRow.session_id == context.session_id,
                ChoiceCardRow.source_run_id == context.run_id,
                ChoiceCardRow.expected_revision == revision,
                ChoiceCardRow.kind == kind,
            )
            .order_by(ChoiceCardRow.created_at.desc())
        )
        for old in existing:  # 同轮同版本同题目重复展示复用原卡，题目不同则新建并取代旧卡
            if shown is None or card_from_row(old, revision).form == shown:
                return await choice_view(db, context.user_id, old, request.revision)
        if kind not in {"pace", "form"} or (kind == "form") != (groups is not None):
            raise ServiceError(422, "validation", "当前没有此类型的待确认选择")
        card = ChoiceCard(
            kind=kind,
            session_id=context.session_id,
            source_run_id=context.run_id,
            expected_revision=revision,
            question="请确认以下信息，再继续规划" if shown else "你希望以什么节奏旅行？",
            options=(ChoiceOption(option_id="confirm", label="确认并继续", value="confirm"),)
            if shown
            else pace_options(),
            form=shown,
        )
        if shown:
            await self.supersede_forms(db, context)
        db.add(
            ChoiceCardRow(
                id=card.choice_id,
                session_id=card.session_id,
                source_run_id=card.source_run_id,
                kind=card.kind,
                expected_revision=card.expected_revision,
                created_at=card.created_at,
                content={
                    "question": card.question,
                    "options": [option.model_dump(mode="json") for option in card.options],
                    **({"form": shown.model_dump(mode="json")} if shown else {}),
                },
            )
        )
        await db.flush()
        return card

    async def supersede_forms(self, db: AsyncSession, context: RunContext) -> None:
        for previous in await open_forms(db, context):
            previous.content = {**previous.content, "superseded": True}

    async def get(self, user_id: UUID, session_id: UUID, choice_id: UUID) -> ChoiceCard:
        async with transaction(self.travel.database) as db:
            row = await owned_card(db, user_id, session_id, choice_id, lock=False)
            request = request_from_row(
                await requests.read_request(db, RunContext(user_id, session_id))
            )
            return await choice_view(db, user_id, row, request.revision)

    async def confirm_from_text(
        self, db: AsyncSession, context: RunContext, request: TravelRequest
    ) -> None:
        cards = await open_forms(db, context, lock=True)
        if not cards or cards[0].source_run_id == context.run_id:
            raise ServiceError(
                422, "validation", "请等待用户回答上一轮的出行安排确认，不得代用户确认"
            )
        form = card_from_row(cards[0], request.revision).form
        assert form is not None
        keys = {group.key for group in form.groups}
        if form.purpose != "trip_ask" and (
            ("transport" in keys and request.transport is None)
            or ("pace" in keys and pace_of(request) is None)
        ):
            raise ServiceError(422, "validation", "请先记录用户明确的交通与旅行节奏")
        cards[0].answered_option_id, cards[0].answered_run_id = "confirm", context.run_id

    async def propose_budget(
        self,
        context: RunContext,
        request: TravelRequest,
        diagnosis: HotelSearchDiagnostics,
        *,
        expires_at: datetime | None = None,
    ) -> ChoiceCard | None:
        if (
            diagnosis.applied_upper is None
            or diagnosis.original_upper is None
            or request.lodging_budget is None
        ):
            raise ServiceError(422, "validation", "没有经过核实的预算放宽方案")
        async with transaction(self.travel.database) as db:
            current = request_from_row(await requests.owned_request(db, context))
            require_revision(current, request.revision)
            await conversation.require_current_run(db, context)
            lodging = request.lodging_budget
            assert lodging.amount.upper
            proposed = (lodging.amount.upper * (diagnosis.tier or 1)).quantize(
                Decimal("0.01"), rounding=ROUND_CEILING
            )
            declined = await db.scalar(
                select(ChoiceCardRow.id).where(
                    ChoiceCardRow.session_id == context.session_id,
                    ChoiceCardRow.kind == "budget_relaxation",
                    ChoiceCardRow.expected_revision == request.revision,
                    ChoiceCardRow.content["proposed_upper"].astext == str(proposed),
                    ChoiceCardRow.answered_option_id == "keep",
                )
            )
            if declined is not None:
                diagnosis.declined = True
                diagnosis.message = (
                    f"已查看¥{diagnosis.applied_upper}档的报价，但用户已拒绝这一金额的放宽；"
                    "原预算保持不变。不要重复建议或提及预算确认卡，改给原预算下的替代方向。"
                )
                return None
            existing = await db.scalar(
                select(ChoiceCardRow).where(
                    ChoiceCardRow.session_id == context.session_id,
                    ChoiceCardRow.source_run_id == context.run_id,
                    ChoiceCardRow.kind == "budget_relaxation",
                    ChoiceCardRow.expected_revision == request.revision,
                    ChoiceCardRow.content["proposed_upper"].astext == str(proposed),
                )
            )
            if existing:
                return card_from_row(existing, request.revision)
            card = ChoiceCard(
                kind="budget_relaxation",
                session_id=context.session_id,
                source_run_id=context.run_id,
                expected_revision=request.revision,
                expires_at=expires_at,
                question="原住宿预算过紧；是否接受放宽？全程所有住宿段共用此上限。",
                options=(
                    ChoiceOption(
                        option_id="accept",
                        label=f"接受每间每晚¥{diagnosis.applied_upper}（全程共用）",
                        value="accept",
                    ),
                    ChoiceOption(
                        option_id="keep",
                        label=f"保持每间每晚¥{diagnosis.original_upper}，换其他方案",
                        value="keep",
                    ),
                ),
            )
            db.add(
                ChoiceCardRow(
                    id=card.choice_id,
                    session_id=context.session_id,
                    source_run_id=context.run_id,
                    kind=card.kind,
                    expected_revision=request.revision,
                    created_at=card.created_at,
                    content={
                        "question": card.question,
                        "options": [o.model_dump(mode="json") for o in card.options],
                        "proposed_upper": str(proposed),
                        "expires_at": card.expires_at.isoformat() if card.expires_at else None,
                    },
                )
            )
            await db.flush()
            return card

    async def accept(
        self,
        db: AsyncSession,
        context: RunContext,
        card: ChoiceCardRow,
        selection: ChoiceSelection,
        revision: int,
    ) -> str:
        if card.answered_option_id is not None:
            raise ServiceError(409, "conflict", "此选择已经回答，请读取原结果")
        request = request_from_row(await requests.owned_request(db, context))
        require_revision(request, revision)
        if card.kind != "memory_confirm" and (
            card.expected_revision != revision or card_from_row(card, revision).stale
        ):
            raise ServiceError(409, "conflict", "选择卡已过期或条件已变化")
        option = selected_option(card, selection.option_id)
        if card.kind not in {"form", "hotel_assign"} and selection.answers is not None:
            raise ServiceError(422, "validation", "普通选择不能混填表单答案")
        if card.kind == "hotel_assign":
            from backend.services.hotel_selection import answer_assignment

            await answer_assignment(db, context, card, option, selection, request)
        elif card.kind == "budget_relaxation":
            if option.option_id == "accept":
                if request.lodging_budget is None:
                    raise ServiceError(409, "conflict", "住宿预算已变化")
                lodging = request.lodging_budget.model_dump(mode="json")
                lodging["amount"]["upper"] = card.content["proposed_upper"]
                await self.travel.patch_request_in_transaction(
                    db,
                    context,
                    RequestPatch.model_validate(
                        {"expected_revision": revision, "set": {"lodging_budget": lodging}}
                    ),
                    source="user_form",
                )
        elif card.kind == "form":
            form = card_from_row(card, revision).form
            if form is None or selection.answers is None:
                raise ServiceError(422, "validation", "请回答完必填题目后统一确认")
            try:
                patch = form_patch(request, form, selection.answers)
            except ValueError as error:
                raise ServiceError(422, "validation", str(error)) from None
            await self.travel.patch_request_in_transaction(db, context, patch, source="user_form")
            card.content = {
                **card.content,
                "form": answered_form(form, selection.answers).model_dump(mode="json"),
            }
        elif card.kind == "pace":
            await self.travel.patch_request_in_transaction(
                db, context, pace_patch(request, option.value), source="user_form"
            )
        elif card.kind == "memory_confirm":
            await MemoryService(self.travel.database).confirm_in_transaction(
                db, context, card, option.option_id
            )
            card.expected_revision = revision  # 记录本次点击实际校验过的CAS；proposal来源不变。
        else:
            raise ServiceError(422, "validation", "当前选择类型不能提交")
        card.answered_option_id, card.answered_run_id = option.option_id, context.run_id
        return selection_prompt(card, option, selection)


async def owned_card(
    db: AsyncSession, user_id: UUID, session_id: UUID, choice_id: UUID, *, lock: bool = True
) -> ChoiceCardRow:
    """写路径默认锁会话与卡片；只读展示传lock=False，不与提交争锁。"""
    if await sessions.get_session(db, user_id, session_id, lock=lock) is None:
        raise ServiceError(404, "blocked", "会话不存在")
    statement = select(ChoiceCardRow).where(
        ChoiceCardRow.id == choice_id, ChoiceCardRow.session_id == session_id
    )
    row = await db.scalar(statement.with_for_update() if lock else statement)
    if row is None:
        raise ServiceError(404, "blocked", "选择卡不存在")
    return row


async def open_forms(
    db: AsyncSession, context: RunContext, *, lock: bool = False
) -> list[ChoiceCardRow]:
    return await open_cards(db, context, "form", lock=lock)


async def open_cards(
    db: AsyncSession, context: RunContext, kind: ChoiceKind, *, lock: bool = False
) -> list[ChoiceCardRow]:
    query = select(ChoiceCardRow).where(
        ChoiceCardRow.session_id == context.session_id,
        ChoiceCardRow.kind == kind,
        ChoiceCardRow.answered_option_id.is_(None),
        ChoiceCardRow.content["superseded"].as_boolean().is_not(True),
    )
    return list(await db.scalars(query.with_for_update() if lock else query))


def card_from_row(row: ChoiceCardRow, revision: int) -> ChoiceCard:
    card = ChoiceCard.model_validate(
        {
            **{
                key: value
                for key, value in row.content.items()
                if key in {"question", "options", "expires_at", "form", "assign"}
            },
            "choice_id": row.id,
            "kind": row.kind,
            "session_id": row.session_id,
            "source_run_id": row.source_run_id,
            "expected_revision": row.expected_revision,
            "created_at": row.created_at,
            "answered_option_id": row.answered_option_id,
        }
    )
    return card.model_copy(
        update={
            "stale": bool(row.content.get("superseded"))
            or row.expected_revision != revision
            or (card.expires_at is not None and card.expires_at <= datetime.now(UTC))
        }
    )


def selected_option(row: ChoiceCardRow, option_id: str) -> ChoiceOption:
    card = card_from_row(row, row.expected_revision)
    option = next((option for option in card.options if option.option_id == option_id), None)
    if option is None:
        raise ServiceError(422, "validation", "选项不属于此选择卡")
    return option


def selection_prompt(
    row: ChoiceCardRow, option: ChoiceOption, selection: ChoiceSelection | None = None
) -> str:
    if row.kind == "form":
        if selection is None or selection.answers is None:
            raise ServiceError(422, "validation", "请回答完必填题目后统一确认")
        shown = row.content.get("form")
        if isinstance(shown, dict) and shown.get("purpose") == "trip_ask":
            return trip_ask_prompt(ChoiceForm.model_validate(shown), selection.answers)
        answers = json.dumps(selection.answers, ensure_ascii=False, sort_keys=True)
        return (
            f"用户统一确认：{answers}。答案已在服务端原子记录，以当前request为准；"
            "不重复追问已确认项，其他必填条件齐全后继续原任务。"
        )
    if row.kind == "hotel_assign":
        assign = row.content.get("assign")
        city = assign.get("city") if isinstance(assign, dict) else None
        if option.option_id == "confirm":
            return (
                f"用户确认把酒店归入{city}的住宿段，服务端已按选择校验并记录。"
                "以服务端酒店选择状态为准：各住宿段选齐则继续规划，否则请用户选择尚未选的住宿段。"
            )
        if option.option_id == "deny":
            typed = selection.answers.get("city", ()) if selection and selection.answers else ()
            return (
                f"用户说这家酒店应归入「{typed[0] if typed else ''}」的住宿段，答案已保存；"
                "请立即调用select_hotel_from_chat完成归段，不要再追问城市。"
            )
        return "用户选择先不选这家酒店。不要自动替用户选择；可请用户另选或贴乐天链接。"
    if row.kind == "memory_confirm":
        return (
            f"用户选择记忆「{row.content.get('question', '')}」：{option.label}。"
            "以服务端memory事实为准，继续当前任务；"
            "不能重新提出这条记忆或自动修改旅行条件。"
        )
    return (
        f"用户选择节奏：{option.value}，请继续未完成的任务。"
        if row.kind == "pace"
        else (
            f"用户选择：{option.label}。预算是否更新以服务端当前条件为准；"
            "沿用有效报价继续未完成的任务，不重新查询未过期报价。"
        )
    )


async def choice_view(
    db: AsyncSession, user_id: UUID, row: ChoiceCardRow, revision: int
) -> ChoiceCard:
    if row.kind != "memory_confirm":
        return card_from_row(row, revision)
    fact = await memory.owned(db, user_id, UUID(str(row.content["fact_id"])))
    if fact is None:
        raise ServiceError(404, "blocked", "记忆事实不存在")
    view = MemoryService.card(row, fact, revision)
    target_id = row.content.get("target_fact_id")
    if row.answered_option_id is None and target_id:
        target = await memory.owned(db, user_id, UUID(str(target_id)))
        if target is None or target.status != "active":
            view = view.model_copy(update={"stale": True})
    if row.answered_option_id is None and fact.status == "proposed":
        current = await memory.active(db, user_id, row.session_id)
        same = [
            other
            for other in current
            if other.key == fact.key
            and other.scope == fact.scope
            and str(other.id) != str(target_id)
        ]
        if (fact.key not in {"interest", "avoid"} and same) or (
            fact.value is not None and any(other.value == fact.value for other in same)
        ):
            view = view.model_copy(update={"stale": True})
    return view


def trip_ask_prompt(form: ChoiceForm, answers: dict[str, tuple[str, ...]]) -> str:
    """合并卡提交后的运行提示：只列用户实际答的组(含不确定)，不带内部选项编号。"""
    parts = []
    for group in form.groups:
        labels = {option.option_id: option.label for option in group.options}
        typed = answers.get(f"{group.key}_text")
        picked = [labels[i] for i in answers.get(group.key, ()) if i in labels]
        if typed:
            picked.append(typed[0].strip())
        if picked:
            parts.append(f"{group.label}：{'、'.join(picked)}")
    return (
        "用户已在合并卡确认出行信息（"
        + ("；".join(parts) or "全部未选，等同不确定")
        + "）。答案已在服务端原子记录，以当前request为准；“无要求/不确定”不是限制，"
        "节奏不确定按标准假设，到达/离开时间不确定按全天安排。不要再问这些项。"
        "继续原任务：先逐住宿段搜索酒店并展示全部候选，然后停下等用户选择，不自动选酒店。"
    )

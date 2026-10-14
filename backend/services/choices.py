"""服务端选择卡生成/恢复；确认在现有消息事务中调用，不另开写入事务。"""

from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.choices import (
    ChoiceCard as ChoiceCard,
)
from backend.domain.choices import (
    ChoiceKind,
    ChoiceOption,
    ChoiceSelection,
    pace_options,
    pace_patch,
)
from backend.domain.execution import RunContext
from backend.domain.hotel_recovery import HotelSearchDiagnostics
from backend.domain.travel_request import RequestPatch, TravelRequest
from backend.persistence import memory, sessions
from backend.persistence import travel as requests
from backend.persistence.models import ChoiceCardRow
from backend.services import conversation
from backend.services.common import ServiceError, transaction
from backend.services.memory import MemoryService
from backend.services.travel import TravelService, request_from_row, require_revision


class ChoiceService:
    def __init__(self, travel: TravelService) -> None:
        self.travel = travel

    async def create(self, context: RunContext, kind: ChoiceKind, revision: int) -> ChoiceCard:
        async with transaction(self.travel.database) as db:
            return await self.create_in_transaction(db, context, kind, revision)

    async def create_in_transaction(
        self,
        db: AsyncSession,
        context: RunContext,
        kind: ChoiceKind,
        revision: int,
    ) -> ChoiceCard:
        row = await requests.owned_request(db, context)
        if row is None:
            raise ServiceError(404, "blocked", "会话不存在")
        request = request_from_row(row)
        require_revision(request, revision)
        await conversation.require_current_run(db, context)
        existing = await db.scalar(
            select(ChoiceCardRow)
            .where(
                ChoiceCardRow.session_id == context.session_id,
                ChoiceCardRow.source_run_id == context.run_id,
                ChoiceCardRow.expected_revision == revision,
                ChoiceCardRow.kind == kind,
            )
            .order_by(ChoiceCardRow.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            return await choice_view(db, context.user_id, existing, request.revision)
        if kind != "pace":
            raise ServiceError(422, "validation", "当前没有此类型的待确认选择")
        card = ChoiceCard(
            kind=kind,
            session_id=context.session_id,
            source_run_id=context.run_id,
            expected_revision=revision,
            question="你希望以什么节奏旅行？",
            options=pace_options(),
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
                },
            )
        )
        await db.flush()
        return card

    async def get(self, user_id: UUID, session_id: UUID, choice_id: UUID) -> ChoiceCard:
        async with transaction(self.travel.database) as db:
            row = await owned_card(db, user_id, session_id, choice_id)
            request = request_from_row(
                await requests.owned_request(db, RunContext(user_id, session_id))
            )
            return await choice_view(db, user_id, row, request.revision)

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
        if card.kind == "budget_relaxation":
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
        return selection_prompt(card, option)


async def owned_card(
    db: AsyncSession, user_id: UUID, session_id: UUID, choice_id: UUID
) -> ChoiceCardRow:
    if await sessions.get_session(db, user_id, session_id, lock=True) is None:
        raise ServiceError(404, "blocked", "会话不存在")
    row = await db.scalar(
        select(ChoiceCardRow)
        .where(ChoiceCardRow.id == choice_id, ChoiceCardRow.session_id == session_id)
        .with_for_update()
    )
    if row is None:
        raise ServiceError(404, "blocked", "选择卡不存在")
    return row


def card_from_row(row: ChoiceCardRow, revision: int) -> ChoiceCard:
    card = ChoiceCard.model_validate(
        {
            **{
                key: value
                for key, value in row.content.items()
                if key in {"question", "options", "expires_at"}
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
            "stale": row.expected_revision != revision
            or (card.expires_at is not None and card.expires_at <= datetime.now(UTC))
        }
    )


def selected_option(row: ChoiceCardRow, option_id: str) -> ChoiceOption:
    card = card_from_row(row, row.expected_revision)
    option = next((option for option in card.options if option.option_id == option_id), None)
    if option is None:
        raise ServiceError(422, "validation", "选项不属于此选择卡")
    return option


def selection_prompt(row: ChoiceCardRow, option: ChoiceOption) -> str:
    if row.kind == "memory_confirm":
        return (
            f"用户选择记忆：{option.label}。以服务端memory事实为准，继续当前任务；"
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

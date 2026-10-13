"""用户原话提议、卡片确认与遗忘；不构造LLM调用或SDK缓存。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.choices import ChoiceCard, ChoiceOption
from backend.domain.execution import RunContext
from backend.domain.memory import (
    KEY_LABELS,
    VALUE_LABELS,
    MemoryFactView,
    MemoryProposal,
    normalize_quote,
    quote_matches,
)
from backend.domain.preferences import Preferences, PreferenceVersion
from backend.persistence import memory, runs, sessions, travel
from backend.persistence.database import Database
from backend.persistence.models import ChoiceCardRow, MemoryFactRow, UserRow
from backend.persistence.user_profile import invalidate as invalidate_profile
from backend.services.common import ServiceError, transaction
from backend.services.conversation import require_current_run, save_state, valid_state

__all__ = ["MemoryService", "MemoryFactView", "MemoryProposal"]
SCALAR_KEYS = set(KEY_LABELS) - {"interest", "avoid"}


def fact_view(row: MemoryFactRow) -> MemoryFactView:
    return MemoryFactView.model_validate(
        {
            "fact_id": row.id,
            "key": row.key,
            "value": row.value,
            "scope": row.scope,
            "session_id": row.session_id,
            "status": row.status,
            "source": row.source,
            "source_run_id": row.source_run_id,
            "evidence_quote": row.evidence_quote,
            "valid_from": row.valid_from,
            "invalidated_at": row.invalidated_at,
            "superseded_by": row.superseded_by,
            "last_confirmed_at": row.last_confirmed_at,
            "created_at": row.created_at,
        }
    )


def changed(user: UserRow, *, deleted: bool = False) -> None:
    user.preference_revision += 1
    user.preference_changed_at = datetime.now(UTC)
    user.preference_deleted = deleted
    user.preferences = {}  # 不能给旧代码留下删除前正文。


def erase(row: MemoryFactRow) -> None:
    row.status, row.value, row.evidence_quote = "deleted", None, ""
    row.invalidated_at = datetime.now(UTC)


class MemoryService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def cutoff(user: UserRow) -> datetime | None:
        return max(
            (
                value
                for value in (user.preference_changed_at, user.memory_forgotten_at)
                if value is not None
            ),
            default=None,
        )

    async def checkpoint_allowed(self, context: RunContext, source_run_id: UUID) -> bool:
        async with transaction(self.database) as db:
            user = await sessions.get_user(db, context.user_id)
            if user is None:
                return False
            if user.memory_forgotten_at is None:
                return True
            source = await runs.owned(db, context.user_id, source_run_id)
            return bool(
                source
                and source.session_id == context.session_id
                and source.created_at >= user.memory_forgotten_at
            )

    async def facts(
        self, user_id: UUID, *, include_history: bool = False
    ) -> tuple[MemoryFactView, ...]:
        async with transaction(self.database) as db:
            statement = select(MemoryFactRow).where(MemoryFactRow.user_id == user_id)
            order = (MemoryFactRow.created_at.desc(), MemoryFactRow.ordinal)
            current = list(
                await db.scalars(
                    statement.where(MemoryFactRow.status.in_(("active", "proposed"))).order_by(
                        *order
                    )
                )
            )
            if include_history:
                current.extend(
                    await db.scalars(
                        statement.where(MemoryFactRow.status.not_in(("active", "proposed")))
                        .order_by(*order)
                        .limit(100)
                    )
                )
            return tuple(fact_view(row) for row in current)

    async def get(self, user_id: UUID, fact_id: UUID) -> MemoryFactView:
        async with transaction(self.database) as db:
            row = await memory.owned(db, user_id, fact_id)
            if row is None:
                raise ServiceError(404, "blocked", "记忆事实不存在")
            return fact_view(row)

    async def snapshot(self, context: RunContext) -> list[dict[str, object]]:
        async with transaction(self.database) as db:
            return await self.snapshot_in_transaction(db, context)

    @staticmethod
    async def snapshot_in_transaction(
        db: AsyncSession, context: RunContext
    ) -> list[dict[str, object]]:
        rows = await memory.active(db, context.user_id, context.session_id)
        trip_keys = {row.key for row in rows if row.scope == "trip" and row.key in SCALAR_KEYS}
        # trip UPDATE/INVALIDATE只遮盖所引用的长期事实，不把同类其他兴趣一起遮掉。
        overridden: set[str] = set()
        trip_ids = {str(row.id) for row in rows if row.scope == "trip"}
        if trip_ids:
            for content in await db.scalars(
                select(ChoiceCardRow.content).where(
                    ChoiceCardRow.session_id == context.session_id,
                    ChoiceCardRow.kind == "memory_confirm",
                    ChoiceCardRow.content["fact_id"].astext.in_(trip_ids),
                )
            ):
                if content.get("target_fact_id"):
                    overridden.add(str(content["target_fact_id"]))
        return memory.bounded_snapshot(
            [
                row
                for row in rows
                if not (
                    row.scope == "long_term" and (row.key in trip_keys or str(row.id) in overridden)
                )
            ]
        )

    async def propose(
        self, context: RunContext, proposal: MemoryProposal
    ) -> list[dict[str, object]]:
        async with transaction(self.database) as db:
            request = await travel.owned_request(db, context)
            if request is None:
                raise ServiceError(404, "blocked", "会话不存在")
            await require_current_run(db, context)
            run = await runs.owned(db, context.user_id, context.run_id)
            user = await sessions.get_user(db, context.user_id, lock=True)
            assert run and user
            if user.memory_forgotten_at is not None and run.created_at < user.memory_forgotten_at:
                raise ServiceError(409, "conflict", "用户已遗忘偏好，旧执行不能重新提出记忆")
            cards: list[dict[str, object]] = []
            for operation in proposal.ops:
                if run.user_text is None or not quote_matches(run.user_text, operation.quote):
                    raise ServiceError(
                        422,
                        "validation",
                        "记忆引用必须来自本轮用户原话；工具、攻略或AI输出不能作为来源",
                    )
                target = (
                    await memory.owned(db, context.user_id, operation.target_fact_id, lock=True)
                    if operation.target_fact_id
                    else None
                )
                if operation.target_fact_id and (
                    target is None
                    or target.status != "active"
                    or (target.scope == "trip" and target.session_id != context.session_id)
                ):
                    raise ServiceError(404, "blocked", "目标记忆不存在")
                if target and target.key != operation.key:
                    raise ServiceError(422, "validation", "不能改变目标事实的key")
                quote = normalize_quote(operation.quote)
                previous = await db.scalar(
                    select(MemoryFactRow).where(
                        MemoryFactRow.user_id == context.user_id,
                        MemoryFactRow.session_id == context.session_id,
                        or_(MemoryFactRow.key == operation.key, MemoryFactRow.status == "rejected"),
                        MemoryFactRow.evidence_quote == quote,
                        MemoryFactRow.status.in_(("proposed", "rejected")),
                    )
                )
                if previous:
                    if previous.status == "rejected":
                        continue
                    existing = await db.scalar(
                        select(ChoiceCardRow).where(
                            ChoiceCardRow.session_id == context.session_id,
                            ChoiceCardRow.kind == "memory_confirm",
                            ChoiceCardRow.content["fact_id"].astext == str(previous.id),
                        )
                    )
                    if existing:
                        if (
                            previous.value != operation.value
                            or previous.scope != operation.scope
                            or existing.content["operation"] != operation.op
                            or existing.content.get("target_fact_id")
                            != (str(operation.target_fact_id) if operation.target_fact_id else None)
                        ):
                            raise ServiceError(
                                409, "conflict", "同一引用已存在不同的待确认提议，请先处理原卡片"
                            )
                        cards.append(
                            self.card(existing, previous, request.revision).model_dump(mode="json")
                        )
                        continue
                active = await memory.active(
                    db, context.user_id, context.session_id if operation.scope == "trip" else None
                )
                same = [
                    row
                    for row in active
                    if row.key == operation.key and row.scope == operation.scope
                ]
                if operation.op == "ADD" and any(row.value == operation.value for row in same):
                    continue
                if operation.op == "ADD" and operation.key in SCALAR_KEYS and same:
                    raise ServiceError(
                        422, "validation", "此偏好已存在；明确变更请用UPDATE并引用其fact_id"
                    )
                fact = MemoryFactRow(
                    user_id=context.user_id,
                    key=operation.key,
                    value=operation.value,
                    scope=operation.scope,
                    session_id=context.session_id,
                    status="proposed",
                    source="user_utterance",
                    source_run_id=context.run_id,
                    evidence_quote=quote,
                    ordinal=max((row.ordinal for row in same), default=-1) + 1,
                )
                db.add(fact)
                await db.flush()
                card = ChoiceCard(
                    kind="memory_confirm",
                    session_id=context.session_id,
                    source_run_id=context.run_id,
                    expected_revision=request.revision,
                    question="是否保存这条偏好？",
                    options=(
                        ChoiceOption(option_id="remember", label="记住", value="remember"),
                        ChoiceOption(option_id="trip", label="这次而已", value="trip"),
                        ChoiceOption(option_id="reject", label="不要记", value="reject"),
                    ),
                )
                stored = ChoiceCardRow(
                    id=card.choice_id,
                    session_id=context.session_id,
                    source_run_id=context.run_id,
                    kind=card.kind,
                    expected_revision=request.revision,
                    created_at=card.created_at,
                    content={
                        "question": card.question,
                        "options": [o.model_dump(mode="json") for o in card.options],
                        "fact_id": str(fact.id),
                        "operation": operation.op,
                        "target_fact_id": str(operation.target_fact_id)
                        if operation.target_fact_id
                        else None,
                    },
                )
                db.add(stored)
                await db.flush()
                cards.append(self.card(stored, fact, request.revision).model_dump(mode="json"))
            return cards

    @staticmethod
    def card(row: ChoiceCardRow, fact: MemoryFactRow, revision: int) -> ChoiceCard:
        value = (
            VALUE_LABELS.get(str(fact.value), str(fact.value)) if fact.value else "不再沿用此偏好"
        )
        question = (
            f"{KEY_LABELS[fact_view(fact).key]}：{value}。是否保存？"
            if fact.status != "deleted"
            else "这条偏好已删除。"
        )
        return ChoiceCard.model_validate(
            {
                "choice_id": row.id,
                "kind": "memory_confirm",
                "session_id": row.session_id,
                "source_run_id": row.source_run_id,
                "expected_revision": revision,
                "question": question[:200],
                "options": row.content["options"],
                "created_at": row.created_at,
                "answered_option_id": row.answered_option_id,
                "stale": fact.status != "proposed" and row.answered_option_id is None,
            }
        )

    async def confirm_in_transaction(
        self, db: AsyncSession, context: RunContext, card: ChoiceCardRow, option: str
    ) -> None:
        if option not in {"remember", "trip", "reject"}:
            raise ServiceError(422, "validation", "记忆选项不支持")
        user = await sessions.get_user(db, context.user_id, lock=True)
        fact = await memory.owned(
            db, context.user_id, UUID(str(card.content["fact_id"])), lock=True
        )
        if (
            user is None
            or fact is None
            or fact.status != "proposed"
            or fact.session_id != context.session_id
        ):
            raise ServiceError(409, "conflict", "此记忆已变化、已删除或已处理")
        target_id = card.content.get("target_fact_id")
        target = (
            await memory.owned(db, context.user_id, UUID(str(target_id)), lock=True)
            if target_id
            else None
        )
        if target_id and (target is None or target.status != "active"):
            raise ServiceError(409, "conflict", "目标记忆已变化，请重新确认")
        now = datetime.now(UTC)
        if option == "reject":
            fact.status = "rejected"
        else:
            fact.scope = "trip" if option == "trip" else "long_term"
            fact.session_id = context.session_id if fact.scope == "trip" else None
            current = await memory.active(db, context.user_id, context.session_id)
            same = [
                row
                for row in current
                if row.key == fact.key
                and row.scope == fact.scope
                and row.id != (target.id if target else None)
            ]
            if fact.key in SCALAR_KEYS and same:
                raise ServiceError(409, "conflict", "此偏好已有其他确认值，不能覆盖")
            if fact.value is not None and any(row.value == fact.value for row in same):
                raise ServiceError(409, "conflict", "此偏好已确认，不能重复保存")
            if fact.key in {"interest", "avoid"} and len(same) >= 20:
                raise ServiceError(422, "validation", "此类偏好最多20条，请先删除一条")
            trip_override = (
                target is not None and target.scope == "long_term" and fact.scope == "trip"
            )
            if target and not trip_override:
                target.status, target.invalidated_at, target.superseded_by = (
                    "superseded",
                    now,
                    fact.id,
                )
            fact.status = "active"
            fact.valid_from = fact.last_confirmed_at = now
            if card.content["operation"] == "INVALIDATE" and not trip_override:
                fact.status, fact.invalidated_at = "superseded", now
        task_row = await travel.owned_request(db, context)
        carry = None
        if task_row is not None:
            carry, _ = await valid_state(db, task_row, context, after=self.cutoff(user))
        changed(user)
        await invalidate_profile(db, context.user_id)
        if task_row is not None and carry is not None and carry.pending_tasks:
            save_state(
                task_row, carry.model_copy(update={"safe_after": user.preference_changed_at})
            )
        await db.flush()
        await memory.projection(db, context.user_id)  # 容量/兼容值同事务验证，失败全回滚。

    async def delete(self, user_id: UUID, fact_id: UUID, version: PreferenceVersion) -> Preferences:
        async with transaction(self.database) as db:
            user = await sessions.get_user(db, user_id, lock=True)
            fact = await memory.owned(db, user_id, fact_id, lock=True)
            if user is None or fact is None:
                raise ServiceError(404, "blocked", "记忆事实不存在")
            if user.preference_revision != version.expected_revision:
                raise ServiceError(409, "conflict", "偏好版本已变化，请读取最新版本")
            if fact.status != "deleted":
                erase(fact)
                # 引用该事实的pending操作也不能在删除后复活它。
                for proposal in await db.scalars(
                    select(MemoryFactRow).where(
                        MemoryFactRow.user_id == user_id, MemoryFactRow.status == "proposed"
                    )
                ):
                    card = await db.scalar(
                        select(ChoiceCardRow).where(
                            ChoiceCardRow.kind == "memory_confirm",
                            ChoiceCardRow.content["fact_id"].astext == str(proposal.id),
                            ChoiceCardRow.content["target_fact_id"].astext == str(fact.id),
                        )
                    )
                    if card:
                        erase(proposal)
                changed(user)
                await invalidate_profile(db, user_id)
                user.memory_forgotten_at = datetime.now(UTC)
            await db.flush()
            values = await memory.projection(db, user_id)
            return Preferences(**values.model_dump(), revision=user.preference_revision)

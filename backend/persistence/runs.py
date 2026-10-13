"""消息去重与应用事件持久化；读取只能看到本人的TaskRun，SSE不会触发执行。"""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.execution import (
    BusinessResult,
    RunContext,
    RuntimeEvent,
    RuntimeOutcome,
    error_code,
    terminal_event,
)
from backend.domain.plans import PlanDraft
from backend.persistence import plans
from backend.persistence.models import EvidenceRow, RunEventRow, TaskRunRow

ACTIVE = ("running", "cancelling")


async def interrupted(db: AsyncSession) -> list[TaskRunRow]:
    return list(await db.scalars(select(TaskRunRow).where(TaskRunRow.status.in_(ACTIVE))))


async def recover(db: AsyncSession, context: RunContext) -> None:
    """单API启动时裁决旧进程，不重放模型或供应商请求。"""
    row = await owned(db, context.user_id, context.run_id, lock=True)
    if row is None or row.status not in ACTIVE:
        return
    cancelled = row.status == "cancelling"
    row.status = "cancelled" if cancelled else "partial"
    row.error_code = "cancelled" if cancelled else "unavailable"
    row.answer = "原执行进程已退出。已提交的条件、草稿和模拟预订保留；请读取最新状态后继续。"
    row.finished_at = datetime.now(UTC)
    await append_event(
        db,
        RuntimeEvent(
            context,
            "cancelled" if cancelled else "partial",
            text=row.answer,
            code="cancelled" if cancelled else "unavailable",
        ),
    )


async def by_message(db: AsyncSession, session_id: UUID, message_id: UUID) -> TaskRunRow | None:
    return await db.scalar(
        select(TaskRunRow).where(
            TaskRunRow.session_id == session_id, TaskRunRow.client_message_id == message_id
        )
    )


async def active(db: AsyncSession, session_id: UUID) -> bool:
    return (
        await db.scalar(
            select(TaskRunRow.id)
            .where(TaskRunRow.session_id == session_id, TaskRunRow.status.in_(ACTIVE))
            .limit(1)
        )
        is not None
    )


async def recent_completed(
    db: AsyncSession, context: RunContext, *, after: datetime | None = None
) -> list[TaskRunRow]:
    rows = await db.scalars(
        select(TaskRunRow)
        .where(
            TaskRunRow.user_id == context.user_id,
            TaskRunRow.session_id == context.session_id,
            TaskRunRow.id != context.run_id,
            TaskRunRow.status == "completed",
            TaskRunRow.created_at >= after if after is not None else true(),
        )
        .order_by(TaskRunRow.created_at.desc(), TaskRunRow.id)
        .limit(2)
    )
    return list(reversed(list(rows)))


async def create(
    db: AsyncSession, user_id: UUID, session_id: UUID, message_id: UUID, prompt: str, mode: str
) -> TaskRunRow:
    row = TaskRunRow(
        user_id=user_id,
        session_id=session_id,
        client_message_id=message_id,
        prompt=prompt,
        mode=mode,
    )
    db.add(row)
    await db.flush()
    return row


async def owned(
    db: AsyncSession, user_id: UUID, run_id: UUID, *, lock: bool = False
) -> TaskRunRow | None:
    statement = select(TaskRunRow).where(TaskRunRow.id == run_id, TaskRunRow.user_id == user_id)
    return await db.scalar(statement.with_for_update() if lock else statement)


async def append_event(db: AsyncSession, event: RuntimeEvent) -> None:
    row = await owned(db, event.context.user_id, event.context.run_id, lock=True)
    if row is None or row.session_id != event.context.session_id:
        raise ValueError("事件不属于此执行")
    row.last_sequence += 1
    payload: dict[str, object] = json.loads(json.dumps(asdict(event), default=str))
    db.add(RunEventRow(run_id=row.id, sequence=row.last_sequence, payload=payload))


async def events(db: AsyncSession, run_id: UUID, after: int) -> list[RunEventRow]:
    rows = await db.scalars(
        select(RunEventRow)
        .where(
            RunEventRow.run_id == run_id,
            RunEventRow.sequence > after,
        )
        .order_by(RunEventRow.sequence)
        .limit(100)
    )
    return list(rows)


async def presentations(db: AsyncSession, run_id: UUID) -> tuple[dict[str, object], ...]:
    rows = await db.scalars(
        select(RunEventRow)
        .where(
            RunEventRow.run_id == run_id, RunEventRow.payload["kind"].as_string() == "presentation"
        )
        .order_by(RunEventRow.sequence.desc())
        .limit(4)
    )
    return tuple(row.payload for row in reversed(list(rows)))


async def business_result(db: AsyncSession, row: TaskRunRow) -> BusinessResult | None:
    """Last stage result is independent from runtime completion; old success stays unknown."""
    event = await db.scalar(
        select(RunEventRow)
        .where(
            RunEventRow.run_id == row.id,
            RunEventRow.payload["kind"].as_string().in_(("tool_started", "tool_finished")),
            RunEventRow.payload["tool_name"].as_string() == "stage_plan_change",
        )
        .order_by(RunEventRow.sequence.desc())
        .limit(1)
    )
    if event is None:
        return None if row.status in ACTIVE else BusinessResult("answer_only")
    if event.payload.get("kind") == "tool_started":
        # The draft transaction can commit before its observed result is recorded.
        return None
    data = event.payload.get("business_result")
    if not isinstance(data, dict):
        code = event.payload.get("code")
        return (
            BusinessResult("stage_failed", code=error_code(code), reason="other") if code else None
        )
    try:
        result = TypeAdapter(BusinessResult).validate_python(data)
    except ValidationError:
        return None
    if result.kind == "stage_failed":
        return result
    if result.kind != "draft_staged":
        return None
    assert result.draft_id is not None
    draft = await plans.draft(db, row.user_id, result.draft_id)
    if draft is None or draft.session_id != row.session_id or draft.plan_id != result.plan_id:
        return None
    if draft.confirmed_version is not None:
        return BusinessResult("confirmed", plan_id=draft.plan_id, version=draft.confirmed_version)
    return result


async def finish(db: AsyncSession, context: RunContext, outcome: RuntimeOutcome) -> None:
    row = await owned(db, context.user_id, context.run_id, lock=True)
    if row is None:
        raise ValueError("执行不存在")
    if row.status not in ACTIVE:
        return
    if row.status == "cancelling":
        outcome = RuntimeOutcome(text=outcome.text, code="cancelled", reason="cancelled")
    encoded = outcome.text.encode("utf-8")
    truncated = len(encoded) > 32768
    if truncated:
        outcome = replace(outcome, text=encoded[:32768].decode("utf-8", errors="ignore"))
    references = await answer_references(db, context)
    event = replace(
        terminal_event(context, outcome),
        evidence_ids=tuple(str(ref) for ref in references),
        answer_truncated=truncated,
    )
    # 不变量：取消与完成竞争通过同一行锁裁决，终态和终态事件在一个事务提交。
    row.status = event.kind
    row.error_code, row.answer = outcome.code, outcome.text
    row.finished_at = datetime.now(UTC)
    await append_event(db, event)


async def answer_references(db: AsyncSession, context: RunContext) -> tuple[UUID, ...]:
    """回答引用存到既有终态事件 JSON；不另建状态列，且只接受本人证据引用。"""
    payloads = await db.scalars(
        select(RunEventRow.payload).where(
            RunEventRow.run_id == context.run_id,
            RunEventRow.payload["kind"].as_string() == "presentation",
        )
    )
    ids: set[UUID] = set()
    for payload in payloads:
        presentation = payload.get("presentation")
        data = presentation.get("data") if isinstance(presentation, dict) else None
        if not isinstance(data, dict):
            continue
        ids.update(await itinerary_references(db, context, data))
        values: list[object] = []
        for key in ("offer_ids", "evidence_ids"):
            refs = data.get(key)
            if isinstance(refs, list):
                values.extend(refs)
        cards = data.get("cards")
        if isinstance(cards, list):
            values.extend(card.get("evidence_id") for card in cards if isinstance(card, dict))
        for value in values:
            if isinstance(value, str):
                try:
                    ids.add(UUID(value))
                except ValueError:
                    continue
    owned_ids = await db.scalars(
        select(EvidenceRow.id).where(
            EvidenceRow.id.in_(ids),
            EvidenceRow.user_id == context.user_id,
            EvidenceRow.session_id == context.session_id,
        )
    )
    return tuple(sorted(owned_ids))


async def itinerary_references(
    db: AsyncSession, context: RunContext, data: dict[str, object]
) -> tuple[UUID, ...]:
    """裁剪后的行程卡只给业务ID；复用本人草稿/版本推导引用，不保存Google卡正文。"""
    draft_id, plan_id = data.get("draft_id"), data.get("plan_id")
    try:
        if isinstance(draft_id, str):
            row = await plans.draft(db, context.user_id, UUID(draft_id))
            if row is None or row.session_id != context.session_id:
                return ()
            draft = PlanDraft.model_validate(row.payload)
            return draft.content.proposal(draft.request_revision).evidence_ids()
        if isinstance(plan_id, str):
            plan = await plans.owned(db, context.user_id, UUID(plan_id))
            if plan is None or plan.session_id != context.session_id:
                return ()
            saved = await plans.version(db, plan)
            if saved:
                return saved.content.proposal(saved.request_revision).evidence_ids()
    except ValueError:
        # 旧/无效引用不能使整轮回答的 finish 失败；不猜测其他会话或版本。
        return ()
    return ()


async def answer_metadata(db: AsyncSession, row: TaskRunRow) -> tuple[int, bool]:
    """读回终态引用，报价缺失/过期/已失效均显示时效提醒；不调用供应商。"""
    payload = await db.scalar(
        select(RunEventRow.payload)
        .where(
            RunEventRow.run_id == row.id,
            RunEventRow.payload["kind"]
            .as_string()
            .in_(("completed", "failed", "partial", "cancelled", "awaiting_user")),
        )
        .order_by(RunEventRow.sequence.desc())
        .limit(1)
    )
    if not isinstance(payload, dict):
        return 0, False
    refs = payload.get("evidence_ids", [])
    ids: set[UUID] = set()
    if isinstance(refs, list):
        for ref in refs:
            if isinstance(ref, str):
                try:
                    ids.add(UUID(ref))
                except ValueError:
                    continue
    records = await db.scalars(
        select(EvidenceRow).where(
            EvidenceRow.id.in_(ids),
            EvidenceRow.user_id == row.user_id,
            EvidenceRow.session_id == row.session_id,
        )
    )
    from backend.persistence.travel import evidence_from_row

    now = datetime.now(UTC)
    found = list(records)
    stale = (
        len(ids)
        - len(found)
        + sum(
            record.invalidated or evidence_from_row(record).valid_until <= now for record in found
        )
    )
    return stale, payload.get("answer_truncated") is True

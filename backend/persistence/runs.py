"""消息去重与应用事件持久化；读取只能看到本人的TaskRun，SSE不会触发执行。"""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.execution import RunContext, RuntimeEvent, RuntimeOutcome, terminal_event
from backend.persistence.models import RunEventRow, TaskRunRow

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


async def finish(db: AsyncSession, context: RunContext, outcome: RuntimeOutcome) -> None:
    row = await owned(db, context.user_id, context.run_id, lock=True)
    if row is None:
        raise ValueError("执行不存在")
    if row.status not in ACTIVE:
        return
    if row.status == "cancelling":
        outcome = RuntimeOutcome(text=outcome.text, code="cancelled", reason="cancelled")
    event = terminal_event(context, outcome)
    # 不变量：取消与完成竞争通过同一行锁裁决，终态和终态事件在一个事务提交。
    row.status = event.kind
    row.error_code, row.answer = outcome.code, outcome.text
    row.finished_at = datetime.now(UTC)
    await append_event(db, event)

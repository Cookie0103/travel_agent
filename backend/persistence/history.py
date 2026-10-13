"""归属隔离的旅行与轮次分页；只查已有事实，不写状态或触发执行。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.persistence.models import (
    PlanRow,
    PlanVersionRow,
    RunEventRow,
    SessionRow,
    TaskRunRow,
    TravelRequestRow,
)

Boundary = tuple[datetime, UUID]


@dataclass(frozen=True)
class SessionHistoryRow:
    session: SessionRow
    conditions: dict[str, object] | None
    plan_id: UUID | None
    current_version: int | None
    saved_at: str | None
    run_activity: datetime | None


async def session_page(
    db: AsyncSession, user_id: UUID, limit: int, before: Boundary | None
) -> list[SessionHistoryRow]:
    activity = (
        select(func.max(func.greatest(TaskRunRow.created_at, TaskRunRow.finished_at)))
        .where(TaskRunRow.session_id == SessionRow.id, TaskRunRow.user_id == user_id)
        .correlate(SessionRow)
        .scalar_subquery()
    )
    statement = (
        select(
            SessionRow,
            TravelRequestRow.conditions,
            PlanVersionRow.plan_id,
            PlanVersionRow.version,
            PlanVersionRow.payload["saved_at"].as_string(),
            activity,
        )
        .outerjoin(TravelRequestRow, TravelRequestRow.session_id == SessionRow.id)
        .outerjoin(
            PlanRow,
            and_(
                PlanRow.session_id == SessionRow.id,
                PlanRow.user_id == user_id,
                PlanRow.current_version > 0,
            ),
        )
        .outerjoin(
            PlanVersionRow,
            and_(
                PlanVersionRow.plan_id == PlanRow.id,
                PlanVersionRow.version == PlanRow.current_version,
            ),
        )
        .where(SessionRow.user_id == user_id)
        .order_by(SessionRow.created_at.desc(), SessionRow.id.desc())
        .limit(limit + 1)
    )
    if before is not None:
        statement = statement.where(tuple_(SessionRow.created_at, SessionRow.id) < before)
    return [SessionHistoryRow(*row) for row in await db.execute(statement)]


async def run_page(
    db: AsyncSession, user_id: UUID, session_id: UUID, limit: int, before: Boundary | None
) -> list[TaskRunRow]:
    statement = (
        select(TaskRunRow)
        .where(TaskRunRow.user_id == user_id, TaskRunRow.session_id == session_id)
        .order_by(TaskRunRow.created_at.desc(), TaskRunRow.id.desc())
        .limit(limit + 1)
    )
    if before is not None:
        statement = statement.where(tuple_(TaskRunRow.created_at, TaskRunRow.id) < before)
    return list(await db.scalars(statement))


async def export_history(
    db: AsyncSession, user_id: UUID | None, session_id: UUID | None
) -> dict[str, object]:
    """本机运维导出；只读事务、可选用户/会话过滤，不输出供应商响应或令牌。"""
    await db.execute(text("SET TRANSACTION READ ONLY"))
    if await db.scalar(text("SHOW transaction_read_only")) != "on":
        raise ValueError("导出必须运行在只读事务")
    statement = select(SessionRow).order_by(SessionRow.created_at, SessionRow.id)
    if user_id is not None:
        statement = statement.where(SessionRow.user_id == user_id)
    if session_id is not None:
        statement = statement.where(SessionRow.id == session_id)
    result: list[dict[str, object]] = []
    for session in await db.scalars(statement):
        records = await db.scalars(
            select(TaskRunRow)
            .where(TaskRunRow.session_id == session.id, TaskRunRow.user_id == session.user_id)
            .order_by(TaskRunRow.created_at, TaskRunRow.id)
        )
        turns = []
        for run in records:
            payloads = await db.scalars(
                select(RunEventRow.payload)
                .where(
                    RunEventRow.run_id == run.id,
                    RunEventRow.payload["kind"].as_string() == "presentation",
                )
                .order_by(RunEventRow.sequence)
            )
            turns.append(exported_run(run, list(payloads)))
        result.append(
            {
                "session_id": str(session.id),
                "user_id": str(session.user_id),
                "created_at": session.created_at.isoformat(),
                "runs": turns,
            }
        )
    return {"format_version": 1, "read_only": True, "sessions": result}


def exported_run(row: TaskRunRow, payloads: list[dict[str, object]]) -> dict[str, object]:
    references = []
    for payload in payloads:
        presentation = payload.get("presentation")
        data = presentation.get("data") if isinstance(presentation, dict) else None
        if isinstance(data, dict):
            reference = {
                key: data[key]
                for key in (
                    "component",
                    "offer_ids",
                    "evidence_ids",
                    "draft_id",
                    "plan_id",
                    "choice_id",
                )
                if key in data
            }
            ids: set[str] = set()
            for key in ("cards", "segments"):
                values = data.get(key)
                if isinstance(values, list):
                    for value in values:
                        if not isinstance(value, dict):
                            continue
                        evidence_id = value.get("evidence_id")
                        if isinstance(evidence_id, str):
                            ids.add(evidence_id)
                        grouped = value.get("evidence_ids")
                        if isinstance(grouped, list):
                            ids.update(item for item in grouped if isinstance(item, str))
            if ids:
                reference["evidence_ids"] = sorted(ids)
            references.append(reference)
    return {
        "run_id": str(row.id),
        "prompt": row.prompt,
        "answer": row.answer,
        "mode": row.mode,
        "status": row.status,
        "error_code": row.error_code,
        "created_at": row.created_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "presentation_refs": references,
    }

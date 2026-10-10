"""归属隔离的旅行与轮次分页；只查已有事实，不写状态或触发执行。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.persistence.models import (
    PlanRow,
    PlanVersionRow,
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

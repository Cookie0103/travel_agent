"""行程/草稿的所有者过滤与不可变版本SQL；服务持有会话锁后执行写入。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.execution import RunContext
from backend.domain.plans import PlanDraft, SavedPlan
from backend.persistence.models import PlanDraftRow, PlanRow, PlanVersionRow


async def for_session(db: AsyncSession, context: RunContext) -> PlanRow | None:
    return await db.scalar(
        select(PlanRow).where(
            PlanRow.session_id == context.session_id, PlanRow.user_id == context.user_id
        )
    )


async def owned(db: AsyncSession, user_id: UUID, plan_id: UUID) -> PlanRow | None:
    return await db.scalar(select(PlanRow).where(PlanRow.id == plan_id, PlanRow.user_id == user_id))


async def draft(db: AsyncSession, user_id: UUID, draft_id: UUID) -> PlanDraftRow | None:
    return await db.scalar(
        select(PlanDraftRow).where(PlanDraftRow.id == draft_id, PlanDraftRow.user_id == user_id)
    )


async def latest_draft(db: AsyncSession, context: RunContext) -> PlanDraftRow | None:
    return await db.scalar(
        select(PlanDraftRow)
        .where(
            PlanDraftRow.user_id == context.user_id,
            PlanDraftRow.session_id == context.session_id,
            PlanDraftRow.confirmed_version.is_(None),
        )
        .order_by(PlanDraftRow.payload["expires_at"].astext.desc(), PlanDraftRow.id)
        .limit(1)
    )


async def version(db: AsyncSession, row: PlanRow, number: int | None = None) -> SavedPlan | None:
    record = await db.get(
        PlanVersionRow, (row.id, row.current_version if number is None else number)
    )
    return SavedPlan.model_validate(record.payload) if record else None


async def add_draft(db: AsyncSession, context: RunContext, value: PlanDraft) -> None:
    db.add(
        PlanDraftRow(
            id=value.draft_id,
            plan_id=value.plan_id,
            user_id=context.user_id,
            session_id=context.session_id,
            confirmed_version=None,
            payload=value.model_dump(mode="json"),
        )
    )
    await db.flush()


async def save(db: AsyncSession, row: PlanRow, value: SavedPlan) -> None:
    db.add(
        PlanVersionRow(plan_id=row.id, version=value.version, payload=value.model_dump(mode="json"))
    )
    row.current_version = value.version
    await db.flush()

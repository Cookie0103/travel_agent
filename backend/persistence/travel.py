"""旅行条件与证据的SQL操作；会话行锁把版本更新和证据失效放在同一事务。"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.evidence import EvidenceKind, EvidenceRecord
from backend.domain.execution import RunContext
from backend.domain.travel_request import TravelRequest
from backend.persistence.models import EvidenceRow, TravelRequestRow
from backend.persistence.sessions import get_session


async def owned_request(db: AsyncSession, context: RunContext) -> TravelRequestRow | None:
    if await get_session(db, context.user_id, context.session_id, lock=True) is None:
        return None
    await db.execute(
        insert(TravelRequestRow)
        .values(session_id=context.session_id, revision=0, conditions={}, source_turn_id=None)
        .on_conflict_do_nothing(index_elements=[TravelRequestRow.session_id])
    )
    return await db.get(TravelRequestRow, context.session_id)


async def update_request(
    db: AsyncSession,
    row: TravelRequestRow,
    request: TravelRequest,
    invalidated: frozenset[str],
    source_turn_id: UUID,
) -> None:
    row.revision = request.revision
    row.conditions = request.model_dump(mode="json", exclude={"revision"})
    row.source_turn_id = source_turn_id
    if invalidated:
        await db.execute(
            update(EvidenceRow)
            .where(EvidenceRow.session_id == row.session_id, EvidenceRow.kind.in_(invalidated))
            .values(invalidated=True)
        )


async def add_evidence(
    db: AsyncSession, context: RunContext, records: Sequence[EvidenceRecord]
) -> None:
    db.add_all(
        EvidenceRow(
            id=record.evidence_id,
            user_id=context.user_id,
            session_id=context.session_id,
            kind=record.kind,
            payload=record.model_dump(mode="json"),
        )
        for record in records
    )
    await db.flush()


async def find_evidence(
    db: AsyncSession, context: RunContext, ids: Sequence[UUID]
) -> list[EvidenceRow]:
    rows = await db.scalars(
        select(EvidenceRow).where(
            EvidenceRow.id.in_(ids),
            EvidenceRow.user_id == context.user_id,
            EvidenceRow.session_id == context.session_id,
        )
    )
    return list(rows)


async def recent_evidence(
    db: AsyncSession, context: RunContext, revision: int
) -> list[EvidenceRow]:
    rows = await db.scalars(
        select(EvidenceRow)
        .where(
            EvidenceRow.user_id == context.user_id,
            EvidenceRow.session_id == context.session_id,
            EvidenceRow.invalidated.is_(False),
            EvidenceRow.payload["request_revision"].as_integer() == revision,
        )
        .order_by(EvidenceRow.payload["retrieved_at"].as_string().desc(), EvidenceRow.id)
        .limit(20)
    )
    return list(rows)


async def entity_evidence(
    db: AsyncSession, context: RunContext, kind: EvidenceKind, ids: Sequence[str]
) -> list[EvidenceRow]:
    rows = await db.scalars(
        select(EvidenceRow).where(
            EvidenceRow.user_id == context.user_id,
            EvidenceRow.session_id == context.session_id,
            EvidenceRow.kind == kind,
            EvidenceRow.payload["entity_id"].as_string().in_(ids),
        )
    )
    return list(rows)

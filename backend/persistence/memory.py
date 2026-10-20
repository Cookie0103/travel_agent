"""事实的owner限定查询与兼容偏好投影；旧JSON不再参与读取。"""

import json
from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.preferences import PreferenceValues
from backend.domain.travel_request import Transport
from backend.persistence.models import MemoryFactRow


def bounded_snapshot(rows: Sequence[MemoryFactRow]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in rows:
        item = {"fact_id": str(row.id), "key": row.key, "value": row.value, "scope": row.scope}
        if len(result) == 30 or len(json.dumps([*result, item], ensure_ascii=False)) > 2000:
            break
        result.append(item)
    return result


async def active(
    db: AsyncSession, user_id: UUID, session_id: UUID | None = None
) -> list[MemoryFactRow]:
    scope = MemoryFactRow.scope == "long_term"
    if session_id is not None:
        scope = or_(
            scope, (MemoryFactRow.scope == "trip") & (MemoryFactRow.session_id == session_id)
        )
    return list(
        await db.scalars(
            select(MemoryFactRow)
            .where(MemoryFactRow.user_id == user_id, MemoryFactRow.status == "active", scope)
            .order_by(MemoryFactRow.ordinal, MemoryFactRow.created_at, MemoryFactRow.id)
        )
    )


async def transport_default(
    db: AsyncSession, user_id: UUID, session_id: UUID | None
) -> tuple[Transport, str] | None:
    """已确认的交通偏好(值, scope)：本会话trip优先于长期；只在request未写交通时作默认。"""
    rows = [
        row
        for row in await active(db, user_id, session_id)
        if row.key == "transport" and row.value in {"walk", "transit", "taxi"}
    ]
    rows.sort(key=lambda row: row.scope == "trip")  # 稳定排序：trip排最后，取最后一个
    return (cast(Transport, rows[-1].value), rows[-1].scope) if rows else None


async def projection(db: AsyncSession, user_id: UUID) -> PreferenceValues:
    rows = await active(db, user_id)
    return PreferenceValues.model_validate(
        {
            "interests": [row.value for row in rows if row.key == "interest"],
            "soft_constraints": [row.value for row in rows if row.key == "avoid"],
            "transport": next(
                (row.value for row in reversed(rows) if row.key == "transport"), None
            ),
        }
    )


async def owned(
    db: AsyncSession, user_id: UUID, fact_id: UUID, *, lock: bool = False
) -> MemoryFactRow | None:
    statement = select(MemoryFactRow).where(
        MemoryFactRow.user_id == user_id, MemoryFactRow.id == fact_id
    )
    return await db.scalar(statement.with_for_update() if lock else statement)

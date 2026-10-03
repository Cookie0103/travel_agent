"""快照入库与读取；一笔事务幂等写入，CLI和旅行工具共用此仓储。"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.catalog import Article, Place
from backend.persistence.models import CatalogRow


async def import_catalog(db: AsyncSession, entries: Sequence[Place | Article]) -> int:
    for entry in entries:
        kind, key = (
            ("places", entry.place_id)
            if isinstance(entry, Place)
            else ("articles", entry.article_id)
        )
        statement = insert(CatalogRow).values(
            id=key, kind=kind, city=entry.city, payload=entry.model_dump(mode="json")
        )
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[CatalogRow.id],
                set_={
                    "payload": statement.excluded.payload,
                    "kind": statement.excluded.kind,
                    "city": statement.excluded.city,
                },
            )
        )
    return len(entries)


async def load_catalog(db: AsyncSession) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {"places": [], "articles": []}
    rows = await db.scalars(select(CatalogRow).order_by(CatalogRow.id))
    for row in rows:
        result[row.kind].append(row.payload)
    return result

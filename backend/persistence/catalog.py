"""快照入库与读取；一笔事务幂等写入，CLI和旅行工具共用此仓储。"""

from collections.abc import Sequence

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.catalog import Article, Place
from backend.persistence.models import CatalogRow


async def import_catalog(
    db: AsyncSession, entries: Sequence[Place | Article], *, prune: bool = False
) -> int:
    """upsert；prune=True时把entries视为完整快照，删除其中不再出现的条目(无外键引用目录行)。"""
    if prune and not entries:
        raise ValueError("空快照不能用于清理目录")
    keys: list[str] = []
    for entry in entries:
        kind, key = (
            ("places", entry.place_id)
            if isinstance(entry, Place)
            else ("articles", entry.article_id)
        )
        keys.append(key)
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
    if prune:
        await db.execute(delete(CatalogRow).where(CatalogRow.id.not_in(keys)))
    return len(entries)


async def load_catalog(db: AsyncSession) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {"places": [], "articles": []}
    rows = await db.scalars(select(CatalogRow).order_by(CatalogRow.id))
    for row in rows:
        result[row.kind].append(row.payload)
    return result


async def catalog_stamp(db: AsyncSession) -> tuple[int, int]:
    """目录内容指纹：行数 + 最大xmin(新增/更新都带新事务号)，不读payload；供进程内缓存失效。"""
    row = (
        await db.execute(
            text("SELECT count(*), coalesce(max(xmin::text::bigint), 0) FROM catalog_entries")
        )
    ).one()
    return int(row[0]), int(row[1])

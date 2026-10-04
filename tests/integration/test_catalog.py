"""真实PostgreSQL验证快照导入的重复执行与事务失败回滚。"""

import asyncio

import pytest
from sqlalchemy import URL

from backend.domain.catalog import Place
from backend.persistence.catalog import import_catalog, load_catalog
from backend.persistence.database import Database
from data.import_catalog import load_snapshot

pytestmark = pytest.mark.integration


def test_repeat_snapshot_import_preserves_count_and_source(postgres_url: URL) -> None:
    async def exercise() -> None:
        database = Database(postgres_url)
        entries = load_snapshot()
        try:
            async with database.sessions.begin() as db:
                await import_catalog(db, entries)
                await import_catalog(db, entries)
            async with database.sessions.begin() as db:
                rows = await load_catalog(db)
            assert sum(map(len, rows.values())) == len(entries)
            expected = {e.place_id: e for e in entries if isinstance(e, Place)}
            # 数据库按稳定ID排序，与Overpass响应的数字ID顺序不同。
            for row in rows["places"]:
                assert row["aliases"] == list(expected[str(row["place_id"])].aliases)
                assert row["source"] == expected[str(row["place_id"])].source.model_dump(
                    mode="json"
                )
        finally:
            await database.close()

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(exercise())


def test_failed_import_transaction_does_not_leave_partial_data(postgres_url: URL) -> None:
    async def exercise() -> None:
        database = Database(postgres_url)
        sample = next(e for e in load_snapshot() if isinstance(e, Place))
        failed = sample.model_copy(update={"place_id": "test:rollback"})
        try:
            with pytest.raises(RuntimeError, match="injected"):
                async with database.sessions.begin() as db:
                    await import_catalog(db, [failed])
                    raise RuntimeError("injected failure")
            async with database.sessions.begin() as db:
                rows = await load_catalog(db)
                assert all(p["place_id"] != failed.place_id for p in rows["places"])
        finally:
            await database.close()

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(exercise())

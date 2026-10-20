"""所有PG测试复用专用本地库创建/迁移与有界清理，不触碰开发数据。"""

from collections.abc import Iterator
from datetime import date

import psycopg
import pytest
from sqlalchemy import URL

from backend.domain.repair import Repair
from backend.domain.travel_request import apply_request_patch
from backend.persistence.database import configuration, database_url
from backend.persistence.temporary import isolated_url as isolated_url
from backend.persistence.temporary import temporary_database


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[URL]:
    try:
        with temporary_database(database_url(configuration()), "test") as target:
            yield target
    except psycopg.OperationalError:
        pytest.fail("项目PostgreSQL不可用，请先运行dev db-up；未完成测试库验证", pytrace=False)


@pytest.fixture
def unrepaired(monkeypatch: pytest.MonkeyPatch) -> None:
    """关闭服务端本地修复，单独验证“冲突草稿照样交付、确认照样拒绝”的路径。"""

    async def keep(content, report, facts, **callbacks):  # type: ignore[no-untyped-def]
        return Repair(content, report)

    monkeypatch.setattr("backend.services.plans.repair", keep)


@pytest.fixture
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """夹具行程日期固定在 2026-10；日期校验的“今天”钉在 2026-10-10。"""
    monkeypatch.setattr(
        "backend.services.travel.apply_request_patch",
        lambda current, patch, today: apply_request_patch(current, patch, date(2026, 10, 10)),
    )

"""E3：对外只读MCP的围栏、限流、catalog缓存，以及“只读”的真实边界。"""

import asyncio
from uuid import UUID

import httpx2
import pytest
from sqlalchemy import func, select

from backend.domain.execution import RunContext
from backend.mcp.server import READ_ONLY, create_app
from backend.persistence import catalog as persistence
from backend.persistence.catalog import import_catalog
from backend.persistence.models import BookingRow, EvidenceRow, PlanRow, TravelRequestRow
from backend.services.common import transaction
from backend.services.rate_limit import positive_int
from backend.services.sessions import DemoIdentity, DemoLogin, SessionService
from backend.services.travel import TravelService
from backend.tools.travel import TravelToolExecutor
from data.import_catalog import load_snapshot
from tests.integration.test_mcp_server import mcp_setup as mcp_setup

pytestmark = pytest.mark.integration

MCP_CALL = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "search_content", "arguments": {"city": "京都", "limit": 1}},
}
HEADERS = {"Accept": "application/json, text/event-stream"}
Setup = tuple[asyncio.Runner, SessionService, DemoIdentity, RunContext]


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_remote_result_fences_third_party_text(mcp_setup: Setup) -> None:
    runner, sessions, identity, context = mcp_setup
    app = create_app(sessions)

    async def exercise() -> None:
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app),
                base_url="http://127.0.0.1:8002",
                headers={"Authorization": "Bearer " + identity.token, **HEADERS},
            ) as http,
        ):
            response = await http.post("/mcp/" + str(context.session_id), json=MCP_CALL)
            assert response.status_code == 200
            body = response.json()["result"]
            article = body["structuredContent"]["data"]["articles"][0]
            assert article["title"].startswith("<untrusted_text>")
            assert article["source"]["attribution"].startswith("<untrusted_text>")
            assert article["category"].startswith("<untrusted_text>")
            assert UUID(article["evidence_id"])  # 标识符保持原样
            assert "<untrusted_text>" in body["content"][0]["text"]

    runner.run(exercise())


def test_per_token_rate_limit_returns_429_with_retry_after_and_recovers(mcp_setup: Setup) -> None:
    runner, sessions, identity, context = mcp_setup
    clock = Clock()
    app = create_app(
        sessions, environment={"MCP_RATE_BURST": "3", "MCP_RATE_PER_SECOND": "1"}, clock=clock
    )

    async def exercise() -> None:
        other = await sessions.create_demo_user(DemoLogin())
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app), base_url="http://127.0.0.1:8002"
            ) as http,
        ):
            path = "/mcp/" + str(context.session_id)
            mine = {"Authorization": "Bearer " + identity.token, **HEADERS}
            for _ in range(3):
                assert (await http.post(path, json=MCP_CALL, headers=mine)).status_code != 429
            limited = await http.post(path, json=MCP_CALL, headers=mine)
            assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"
            assert 1 <= int(limited.headers["Retry-After"]) <= 2
            # 其他令牌有自己的桶（越权的404说明已通过认证与限流层）。
            theirs = {"Authorization": "Bearer " + other.token, **HEADERS}
            assert (await http.post(path, json=MCP_CALL, headers=theirs)).status_code == 404
            clock.now += 2
            assert (await http.post(path, json=MCP_CALL, headers=mine)).status_code != 429

    runner.run(exercise())


def test_rate_limit_environment_is_capped() -> None:
    assert positive_int({"MCP_RATE_BURST": "99999"}, "MCP_RATE_BURST", 60, 600) == 600


def test_catalog_is_loaded_once_per_content_version(
    mcp_setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, sessions, identity, context = mcp_setup
    travel = TravelService(sessions.database)
    calls = 0
    original = persistence.load_catalog

    async def counted(db):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return await original(db)

    monkeypatch.setattr("backend.services.catalog.load_catalog", counted)

    async def search() -> None:
        result = await TravelToolExecutor(travel).execute(
            context, "search_places", {"city": "京都", "limit": 1}
        )
        assert result.code is None

    async def exercise() -> None:
        for _ in range(3):
            await search()
        assert calls == 1
        # 目录内容变化后失效重载，新内容可见。
        first = load_snapshot()[0]
        try:
            async with transaction(sessions.database) as db:
                await import_catalog(db, [first.model_copy(update={"city": "测试市"})])
            await search()
            assert calls == 2
        finally:
            async with transaction(sessions.database) as db:
                await import_catalog(db, [first])  # 还原，避免影响会话内其他测试

    runner.run(exercise())


def test_mcp_read_calls_leave_business_state_untouched_but_record_evidence(
    mcp_setup: Setup,
) -> None:
    """“只读”= 不改旅行条件/行程/预订；每次查询仍追加Evidence行(追溯语义不变)。"""
    runner, sessions, identity, context = mcp_setup
    travel = TravelService(sessions.database)

    async def counts() -> tuple[int, int, int, int]:
        async with transaction(sessions.database) as db:
            return (
                await db.scalar(select(func.count()).select_from(EvidenceRow)) or 0,
                await db.scalar(select(func.count()).select_from(PlanRow)) or 0,
                await db.scalar(select(func.count()).select_from(BookingRow)) or 0,
                await db.scalar(select(func.coalesce(func.sum(TravelRequestRow.revision), 0))) or 0,
            )

    async def exercise() -> None:
        before = await counts()
        for definition in READ_ONLY:
            arguments: dict[str, object] = (
                {"city": "京都", "limit": 1}
                if definition.name.startswith("search")
                else {"entity_id": "osm:way/57111281" if "place" in definition.name else "nope"}
            )
            await TravelToolExecutor(travel, max_calls=None).execute(
                context, definition.name, arguments
            )
        after = await counts()
        assert after[0] > before[0]  # Evidence追加
        assert after[1:] == before[1:]  # 行程/预订/条件版本不变

    runner.run(exercise())

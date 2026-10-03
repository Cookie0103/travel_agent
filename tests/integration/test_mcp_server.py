"""R19：真实PG与官方MCP HTTP客户端，契约复用、身份隔离及失败边界。"""

import asyncio
import json
import socket
from collections.abc import Iterator
from uuid import UUID, uuid4

import httpx2
import pytest
import uvicorn
from mcp import Client, types
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import URL

from backend.domain.execution import RunContext
from backend.mcp.server import READ_ONLY, create_app
from backend.persistence.catalog import import_catalog
from backend.services.common import transaction
from backend.services.sessions import DemoIdentity, DemoLogin, SessionService
from backend.services.travel import TravelService
from backend.tools.travel import TravelToolExecutor
from data.import_catalog import load_snapshot

pytestmark = pytest.mark.integration


@pytest.fixture
def mcp_setup(
    postgres_url: URL,
) -> Iterator[tuple[asyncio.Runner, SessionService, DemoIdentity, RunContext]]:
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        sessions = SessionService(postgres_url, demo_enabled=True)
        identity = runner.run(sessions.create_demo_user(DemoLogin()))
        session = runner.run(sessions.new_session(identity.user_id))
        context = RunContext(identity.user_id, session.session_id)
        try:

            async def seed() -> None:
                async with transaction(sessions.database) as db:
                    await import_catalog(db, load_snapshot())

            runner.run(seed())
            yield runner, sessions, identity, context
        finally:
            runner.run(sessions.close())


def payload(result: types.CallToolResult | types.InputRequiredResult) -> dict[str, object]:
    assert isinstance(result, types.CallToolResult) and isinstance(result.structured_content, dict)
    assert result.is_error == (result.structured_content["status"] == "error")
    assert len(result.content) == 1 and isinstance(result.content[0], types.TextContent)
    assert json.loads(result.content[0].text) == result.structured_content
    return dict(result.structured_content)


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_mcp_http_lists_shared_readonly_contract_and_calls_match_direct_tools(
    mcp_setup: tuple[asyncio.Runner, SessionService, DemoIdentity, RunContext], mode: str
) -> None:
    runner, sessions, identity, context = mcp_setup
    app = create_app(sessions)

    async def exercise() -> None:
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app),
                base_url="http://127.0.0.1:8002",
                headers={"Authorization": "Bearer " + identity.token},
            ) as http,
        ):
            url = str(http.base_url.join("/mcp/" + str(context.session_id)))
            async with Client(
                streamable_http_client(url, http_client=http), mode=mode, cache=None
            ) as client:
                listed = await client.list_tools()
                assert {tool.name: tool.input_schema for tool in listed.tools} == {
                    definition.name: definition.schema for definition in READ_ONLY
                }
                for name in ("search_content", "search_places"):
                    arguments = {"city": "京都", "limit": 1}
                    remote = payload(await client.call_tool(name, arguments))
                    direct = await TravelToolExecutor(TravelService(sessions.database)).execute(
                        context, name, arguments
                    )
                    collection = "articles" if name == "search_content" else "places"
                    entries = direct.data[collection]
                    assert isinstance(entries, list)
                    remote_data = remote["data"]
                    assert isinstance(remote_data, dict) and remote["data_mode"] == "snapshot"
                    remote_entries = remote_data[collection]
                    assert isinstance(remote_entries, list)
                    # 两次真实查询生成各自Evidence UUID；事实、状态和来源仍逐字段比较。
                    assert [
                        {k: v for k, v in row.items() if k != "evidence_id"}
                        for row in remote_entries
                    ] == [{k: v for k, v in row.items() if k != "evidence_id"} for row in entries]
                    evidence_ids = remote["evidence_ids"]
                    assert isinstance(evidence_ids, list) and evidence_ids
                    records = await TravelService(sessions.database).resolve_evidence(
                        context, [UUID(value) for value in evidence_ids]
                    )
                    assert len(records) == len(entries)
                    assert [row["evidence_id"] for row in remote_entries] == evidence_ids
                    key = "article_id" if name == "search_content" else "place_id"
                    getter = "get_article" if name == "search_content" else "get_place_facts"
                    facts = payload(await client.call_tool(getter, {"entity_id": entries[0][key]}))
                    assert facts["status"] == "ok"
                empty = payload(await client.call_tool("search_places", {"city": "大阪"}))
                assert empty["status"] == "empty" and empty["error"] is None
                forbidden = payload(await client.call_tool("hold_hotel", {}))
                assert forbidden["error"] == {"code": "blocked", "suggestion": ""}
                for bad_arguments in (
                    {"city": "京都", "limit": True},
                    {"city": "京都", "user_id": str(uuid4())},
                    {},
                ):
                    invalid = payload(await client.call_tool("search_places", bad_arguments))
                    assert (
                        isinstance(invalid["error"], dict)
                        and invalid["error"]["code"] == "validation"
                    )
                missing = payload(await client.call_tool("get_article", {"entity_id": "missing"}))
                assert isinstance(missing["error"], dict) and missing["error"]["code"] == "blocked"

    runner.run(exercise())


def test_mcp_auth_session_host_origin_and_body_limits(
    mcp_setup: tuple[asyncio.Runner, SessionService, DemoIdentity, RunContext],
) -> None:
    runner, sessions, identity, context = mcp_setup
    app = create_app(sessions)

    async def exercise() -> None:
        other = await sessions.create_demo_user(DemoLogin())
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app), base_url="http://127.0.0.1:8002"
            ) as http,
        ):
            path = "/mcp/" + str(context.session_id)
            assert (await http.post(path, json={})).status_code == 401
            assert (
                await http.post(path, json={}, headers={"Authorization": "Bearer invalid"})
            ).status_code == 401
            assert (
                await http.post(path, json={}, headers={"Authorization": "Bearer " + other.token})
            ).status_code == 404
            headers = {"Authorization": "Bearer " + identity.token}
            assert (
                await http.post("/mcp/" + str(uuid4()), json={}, headers=headers)
            ).status_code == 404
            assert (await http.post("/mcp/not-a-uuid", json={}, headers=headers)).status_code == 404
            assert (
                await http.post(path, json={}, headers={**headers, "Host": "attacker.invalid"})
            ).status_code == 421
            assert (
                await http.post(
                    path, json={}, headers={**headers, "Origin": "https://attacker.invalid"}
                )
            ).status_code == 403
            for key, value, status in (
                ("Origin", "http://localhost:8002.attacker.invalid", 403),
                ("Origin", "http://attacker.invalid@localhost:8002", 403),
                ("Origin", "http://localhost:8002/path", 403),
                ("Host", "127.0.0.1:8002.attacker.invalid", 421),
            ):
                assert (
                    await http.post(path, json={}, headers={**headers, key: value})
                ).status_code == status
            too_large = await http.post(
                path, content="x" * 65537, headers={**headers, "Content-Type": "application/json"}
            )
            assert too_large.status_code == 413

    runner.run(exercise())


def test_mcp_database_outage_does_not_disclose_connection(postgres_url: URL) -> None:
    with socket.socket() as socket_guard:
        socket_guard.bind(("127.0.0.1", 0))
        bad_url = postgres_url.set(port=socket_guard.getsockname()[1])
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            sessions = SessionService(bad_url)
            app = create_app(sessions)

            async def exercise() -> None:
                async with (
                    app.router.lifespan_context(app),
                    httpx2.AsyncClient(
                        transport=httpx2.ASGITransport(app), base_url="http://127.0.0.1:8002"
                    ) as http,
                ):
                    response = await http.post(
                        "/mcp/" + str(UUID(int=1)),
                        json={},
                        headers={"Authorization": "Bearer fixture"},
                    )
                    assert response.status_code == 503
                    assert response.json() == {"code": "unavailable", "message": "数据库暂不可用"}

            runner.run(exercise())


def test_mcp_tcp_client_and_tool_dependency_failure_keep_safe_contract(
    mcp_setup: tuple[asyncio.Runner, SessionService, DemoIdentity, RunContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, sessions, identity, context = mcp_setup
    app = create_app(sessions)

    async def unavailable(*arguments: object) -> None:
        raise OSError("private-connection-marker")

    async def exercise() -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="error"))
            task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                async with asyncio.timeout(5):
                    while not server.started:
                        if task.done():
                            await task
                            raise RuntimeError("MCP服务未启动")
                        await asyncio.sleep(0.01)
                url = f"http://127.0.0.1:{listener.getsockname()[1]}/mcp/{context.session_id}"
                async with (
                    httpx2.AsyncClient(
                        headers={"Authorization": "Bearer " + identity.token}, trust_env=False
                    ) as http,
                    Client(streamable_http_client(url, http_client=http), cache=None) as client,
                ):
                    normal = payload(
                        await client.call_tool("search_places", {"city": "京都", "limit": 1})
                    )
                    assert normal["status"] == "ok"
                    monkeypatch.setattr(
                        "backend.services.catalog.CatalogService.query", unavailable
                    )
                    failed = payload(await client.call_tool("search_places", {"city": "京都"}))
                    assert (
                        isinstance(failed["error"], dict)
                        and failed["error"]["code"] == "unavailable"
                    )
                    assert "private-connection-marker" not in str(failed)
                    assert failed["data"] == {} and failed["status"] == "error"
            finally:
                server.should_exit = True
                async with asyncio.timeout(5):
                    await task

    runner.run(exercise())

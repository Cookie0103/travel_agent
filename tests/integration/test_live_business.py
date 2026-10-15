"""R01/R05：API实际运行边界可完成超过旧4HTTP的酒店链路，模型响应全来自本机。"""

import asyncio
import json
from pathlib import Path

import pytest

from backend.domain.execution import RunContext, RuntimeEvent
from backend.mcp.bridge import sdk_tool_name
from backend.providers.claude_agent.application import GuardedRuntime
from backend.providers.claude_agent.environment import worker_environment
from backend.services.travel import TravelService
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_sdk_cli_offline import scripted_response

pytestmark = pytest.mark.integration


def test_api_runtime_completes_six_http_hotel_flow_with_real_sdk_and_pg(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, travel, context = travel_setup
    requests: list[dict[str, object]] = []
    offers: list[str] = []

    def forward(provider: str, key: str, body: bytes) -> tuple[int, bytes]:
        assert provider == "deepseek"
        assert key == "synthetic-local-only"
        request = json.loads(body)
        requests.append(request)
        index = len(requests)
        call: tuple[str, dict[str, object]]
        if index == 1:
            call = "load_skill", {"name": "hotel-comparison"}
        elif index == 2:
            call = "search_hotel_offers", {"expected_revision": 1, "limit": 3}
        else:
            if index == 3:
                results = [
                    b["content"]
                    for m in request["messages"]
                    if isinstance(m.get("content"), list)
                    for b in m["content"]
                    if b.get("type") == "tool_result"
                ]
                content = results[-1]
                data = json.loads(content if isinstance(content, str) else content[0]["text"])
                offers.extend(o["offer_id"] for o in data["data"]["offers"])
                rows = data["data"]["offers"]
                assert len(offers) == 6 and len({row["hotel_id"] for row in rows}) == 3
            if index in {3, 4}:
                call = (
                    "refresh_hotel_offer",
                    {"expected_revision": 1, "offer_id": offers[index - 3]},
                )
            elif index == 5:
                call = (
                    "present_travel_result",
                    {"component": "hotel_comparison", "expected_revision": 1, "offer_ids": offers},
                )
            else:
                assert index == 6
                return scripted_response(body)
        status, content = scripted_response(
            b'{"model":"deepseek-flash","messages":[]}',
            tool_calls=((sdk_tool_name(call[0]), call[1]),),
        )
        return status, content.replace(b'"tool_0"', f'"hotel_step_{index}"'.encode())

    for name, value in {
        "LLM_PROVIDER": "deepseek",
        "DEEPSEEK_API_KEY": "synthetic-local-only",
        "DEEPSEEK_MODEL": "deepseek-flash",
        "DAILY_BUDGET_CNY": "5",
        "DAILY_BUDGET_USD": "0",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("backend.providers.claude_agent.live.forward_messages", forward)

    # 隔离账本仍在tmp_path；被测实际worker加载项目代码，不把临时目录误作源码根。
    def environment(
        source: dict[str, str], directory: Path, root: Path, endpoint: str, token: str, model: str
    ) -> dict[str, str]:
        return worker_environment(
            source, directory, Path(__file__).resolve().parents[2], endpoint, token, model
        )

    monkeypatch.setattr("backend.providers.claude_agent.live.worker_environment", environment)
    events: list[RuntimeEvent] = []

    async def exercise() -> None:
        runtime = GuardedRuntime(
            tmp_path, travel.database.engine.url.render_as_string(hide_password=False)
        )
        outcome = await runtime.execute(
            context, "比较酒店并展示卡片", None, events.append, asyncio.Event()
        )
        assert outcome.code is None and outcome.sdk_session_id

    runner.run(exercise())
    assert len(requests) == 6
    assert [e.tool_name for e in events if e.kind == "tool_finished"] == [
        "load_skill",
        "search_hotel_offers",
        "refresh_hotel_offer",
        "refresh_hotel_offer",
        "present_travel_result",
    ]
    assert all(e.code is None for e in events if e.kind == "tool_finished")
    assert sum(e.kind == "presentation" for e in events) == 1
    report = json.loads(
        (
            tmp_path
            / ".cache/sessions"
            / str(context.user_id)
            / str(context.session_id)
            / "report.json"
        ).read_text(encoding="utf-8")
    )
    assert report["http_attempts"] == 6 and report["guard_failures"] == []
    assert report["trace_status"] == "local_saved"

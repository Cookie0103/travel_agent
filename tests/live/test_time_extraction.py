"""显式授权的真实模型语义回归；默认不调用，不查询旅行供应商。"""

import asyncio
import json
import os
import re
from datetime import time

import pytest
from dotenv import load_dotenv

from backend.domain.execution import RunContext
from backend.domain.travel_request import RequestPatch
from backend.limits import read_budget
from backend.persistence.database import configuration, database_url
from backend.providers.claude_agent.live import run_live
from backend.services.sessions import DemoLogin, SessionService
from backend.services.travel import TravelService
from scripts.dev import ROOT

pytestmark = pytest.mark.live


@pytest.mark.parametrize(
    ("case", "daily", "initial", "expected"),
    [
        ("arrival-return", "", None, None),
        ("daily-start", "每天早上9点开始游玩。", None, time(9)),
        ("correction", "你之前记的每天22点出发是误解，请纠正，我没说每天几点出发。", "22:00", None),
    ],
)
def test_flight_times_do_not_replace_daily_start(
    case: str,
    daily: str,
    initial: str | None,
    expected: time | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("TRAVEL_TIME_PROBE") not in {case, "both"}:
        pytest.skip("须显式选择TRAVEL_TIME_PROBE；每case最多2次模型请求，禁止自动重跑")
    phase = os.environ.get("TRAVEL_TIME_PROBE_PHASE", "after")
    if phase not in {"before", "after"}:
        pytest.fail("TRAVEL_TIME_PROBE_PHASE须为before或after，未调用模型")
    marker = ROOT / ".cache" / f"p89-time-{phase}-{case}.started"
    if marker.exists():
        pytest.fail("该case已有执行记录；先核对结果，不自动重跑")
    load_dotenv(ROOT / ".env", encoding="utf-8")
    monkeypatch.setenv("TRAVEL_PROFILE", "default")
    monkeypatch.setenv(
        "DAILY_BUDGET_CNY", str(min(read_budget(os.environ.get("DAILY_BUDGET_CNY", "")), 15))
    )

    async def prepare() -> tuple[SessionService, TravelService, RunContext]:
        sessions = SessionService(database_url(configuration()), demo_enabled=True)
        identity = await sessions.create_demo_user(DemoLogin(display_name="时间语义回归"))
        session = await sessions.new_session(identity.user_id)
        context = RunContext(identity.user_id, session.session_id)
        travel = TravelService(sessions.database)
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 0,
                    "set": {
                        "city": "冲绳",
                        "start_date": "2026-11-11",
                        "end_date": "2026-11-12",
                        **({"departure_time": initial} if initial is not None else {}),
                    },
                }
            ),
        )
        return sessions, travel, context

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        sessions, travel, context = runner.run(prepare())
        try:
            marker.parent.mkdir(exist_ok=True)
            with marker.open("x", encoding="utf-8") as stream:
                stream.write(str(context.run_id)[:8] + "\n")
            report = run_live(
                "只记录我的旅行条件，不查询任何资料，不规划或生成草稿。"
                "抵达冲绳是11号早上9点，回是12号晚上10点。" + daily,
                context,
                ROOT,
                database_dsn=sessions.database.engine.url.render_as_string(hide_password=False),
                provider="deepseek",
                max_attempts=2,
                real_data=False,
            )
            request = runner.run(travel.get_request(context))
            events = report.get("events", [])
            tools = [
                e.get("tool_name")
                for e in (events if isinstance(events, list) else [])
                if isinstance(e, dict) and e.get("kind") == "tool_finished"
            ]
            print(
                "TIME_PROBE "
                + json.dumps(
                    {
                        "case": case,
                        "run": str(context.run_id)[:8],
                        "status": report.get("status"),
                        "http_attempts": report.get("http_attempts"),
                        "run_accounted_cny": report.get("run_accounted_cny"),
                        "departure_time": str(request.departure_time),
                        "tools": tools,
                    }
                )
            )
            assert report.get("status") == "success"
            assert "update_travel_request" in tools
            assert set(tools) <= {"get_trip_context", "update_travel_request"}
            assert request.departure_time == expected
            assert any(
                "11" in c and re.search(r"(?:0?9:00|9点)", c) for c in request.hard_constraints
            )
            assert any(
                "12" in c and re.search(r"(?:22:00|(?:晚.*)?10点)", c)
                for c in request.hard_constraints
            )
        finally:
            runner.run(sessions.close())

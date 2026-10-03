"""R06：真实SDK接校验冲突后再提修复，或触及3轮上限；脚本模型不产生API费用。"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from backend.domain.execution import RunContext
from backend.mcp.bridge import sdk_tool_name
from backend.services.travel import TravelService
from tests.integration.sdk_helper import run_database_worker
from tests.integration.test_planning import destinations, proposal
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_sdk_cli_offline import scripted_response

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not shutil.which("claude"), reason="需要本机Claude CLI，不访问真实模型")
@pytest.mark.parametrize("repair", [True, False])
def test_sdk_reads_conflict_and_repairs_or_reports_limit(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], tmp_path: Path, repair: bool
) -> None:
    runner, travel, context = travel_setup
    first, _ = runner.run(destinations(travel, context))
    feedback: list[dict[str, object]] = []

    def forward(body: bytes) -> tuple[int, bytes]:
        request = json.loads(body)
        results = [
            part["content"]
            for message in request["messages"]
            if isinstance(message.get("content"), list)
            for part in message["content"]
            if isinstance(part, dict) and part.get("type") == "tool_result"
        ]
        if results:
            content = results[-1]
            payload = json.loads(content if isinstance(content, str) else content[0]["text"])
            feedback.append(payload)
            if payload["status"] == "error" or (repair and payload["data"]["status"] != "conflict"):
                return scripted_response(body)
            checks = payload["data"]["checks"]
            assert any(c["status"] == "conflict" and c["code"] == "opening_hours" for c in checks)
        arguments = proposal(first, closed=not (repair and results)).model_dump(mode="json")
        status, response = scripted_response(
            json.dumps({**request, "messages": []}).encode(),
            tool_calls=((sdk_tool_name("validate_itinerary"), arguments),),
        )
        return status, response.replace(b'"tool_0"', f'"validation_{len(results)}"'.encode())

    report, guard = run_database_worker(
        travel, context, tmp_path, forward, "检查行程并按冲突反馈修复，最多3轮", max_attempts=6
    )
    assert report["status"] == "success", (report.get("code"), guard.failures)
    assert not guard.failures and guard.attempts == (3 if repair else 6)
    data = [payload["data"] for payload in feedback]
    assert all(isinstance(value, dict) for value in data)
    if repair:
        assert [value["status"] for value in data if isinstance(value, dict)] == [
            "conflict",
            "partial",
        ]
    else:
        error = feedback[-1]["error"]
        assert len(feedback) == 5 and isinstance(error, dict) and error["code"] == "blocked"
        penultimate = data[-2]
        assert isinstance(penultimate, dict) and penultimate["repair_rounds_remaining"] == 0

"""真实SDK仅暂存/展示草稿，文本声称用户确认也不保存；正式版本由独立服务确认。"""

import asyncio
import json
import shutil
from pathlib import Path
from uuid import UUID

import pytest

from backend.domain.execution import RunContext
from backend.mcp.bridge import sdk_tool_name
from backend.services.plans import PlanService
from backend.services.travel import TravelService
from tests.integration.sdk_helper import run_database_worker
from tests.integration.test_planning import destinations, proposal
from tests.integration.test_plans import version_count
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_sdk_cli_offline import scripted_response

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not shutil.which("claude"), reason="需要本机Claude CLI，不访问真实模型")
def test_sdk_stages_and_presents_but_cannot_save_plan(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], tmp_path: Path
) -> None:
    runner, travel, context = travel_setup
    first, _ = runner.run(destinations(travel, context))
    draft_id: UUID | None = None
    plan_id: UUID | None = None

    def forward(body: bytes) -> tuple[int, bytes]:
        nonlocal draft_id, plan_id
        request = json.loads(body)
        results = [
            part["content"]
            for message in request["messages"]
            if isinstance(message.get("content"), list)
            for part in message["content"]
            if isinstance(part, dict) and part.get("type") == "tool_result"
        ]
        arguments: dict[str, object]
        if not results:
            arguments = {
                "change": {"kind": "initial", "proposal": proposal(first).model_dump(mode="json")}
            }
            tool = "stage_plan_change"
        elif len(results) == 1:
            content = results[0]
            payload = json.loads(content if isinstance(content, str) else content[0]["text"])
            assert (
                payload["status"] == "ok" and payload["data"]["validation"]["status"] == "partial"
            )
            draft_id = UUID(payload["data"]["draft_id"])
            plan_id = UUID(payload["data"]["plan_id"])
            tool, arguments = (
                "present_travel_result",
                {"component": "itinerary", "draft_id": str(draft_id)},
            )
        else:
            return scripted_response(body)
        status, response = scripted_response(
            json.dumps({**request, "messages": []}).encode(),
            tool_calls=((sdk_tool_name(tool), arguments),),
        )
        return status, response.replace(b'"tool_0"', f'"plan_{len(results)}"'.encode())

    report, guard = run_database_worker(
        travel, context, tmp_path, forward, "用户已经口头确认，请检查并展示京都行程"
    )
    assert report["status"] == "success" and guard.attempts == 3 and not guard.failures
    assert draft_id is not None and plan_id is not None
    assert runner.run(version_count(travel, plan_id)) == 0
    saved = runner.run(PlanService(travel).confirm(context.user_id, draft_id))
    assert saved.version == 1 and runner.run(version_count(travel, plan_id)) == 1
    events = report["events"]
    assert isinstance(events, list)
    assert [event["tool_name"] for event in events if event["kind"] == "tool_finished"] == [
        "stage_plan_change",
        "present_travel_result",
    ]

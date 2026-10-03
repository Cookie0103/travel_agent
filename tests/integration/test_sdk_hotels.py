"""真实SDK自行往返工具：脚本模型先查报价，再引用返回ID补卡；不访问付费API。"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from backend.domain.execution import RunContext
from backend.mcp.bridge import sdk_tool_name
from backend.services.travel import TravelService
from tests.integration.sdk_helper import run_database_worker
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_sdk_cli_offline import scripted_response

pytestmark = pytest.mark.integration


def hotel_response(body: bytes) -> tuple[int, bytes]:
    request = json.loads(body)
    results = [
        part["content"]
        for message in request["messages"]
        if isinstance(message.get("content"), list)
        for part in message["content"]
        if isinstance(part, dict) and part.get("type") == "tool_result"
    ]
    if not results:
        status, response = scripted_response(
            body,
            tool_calls=(
                (sdk_tool_name("search_hotel_offers"), {"expected_revision": 1, "limit": 2}),
            ),
        )
        # SDK按tool_use_id关联结果；各轮调用必须有不同ID。
        return status, response.replace(b"tool_0", b"tool_search")
    if len(results) == 1:
        content = results[0]
        payload = json.loads(content if isinstance(content, str) else content[0]["text"])
        ids = [offer["offer_id"] for offer in payload["data"]["offers"]]
        return scripted_response(
            json.dumps({**request, "messages": []}).encode(),
            tool_calls=(
                (
                    sdk_tool_name("present_travel_result"),
                    {"component": "hotel_comparison", "expected_revision": 1, "offer_ids": ids},
                ),
            ),
        )
    return scripted_response(body)


@pytest.mark.skipif(not shutil.which("claude"), reason="需要本机Claude CLI，不访问真实模型")
def test_sdk_queries_then_presents_database_prices(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
) -> None:
    _, travel, context = travel_setup
    report, guard = run_database_worker(
        travel,
        context,
        tmp_path,
        hotel_response,
        "比较两个模拟酒店的含税总价",
    )
    assert report["status"] == "success", (
        report.get("code"),
        guard.failures,
        guard.failure_details,
    )
    assert guard.attempts == 3 and not guard.failures
    results = report["results"]
    assert isinstance(results, list) and "lowest_offer_ids" in results[0]["outcome"]["text"]
    events = report["events"]
    assert isinstance(events, list)
    assert [event["tool_name"] for event in events if event["kind"] == "tool_finished"] == [
        "search_hotel_offers",
        "present_travel_result",
    ]

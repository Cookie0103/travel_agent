"""R16：真实SDK只暂留，业务PG保存held，没有模型确认工具或订单。"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from backend.domain.execution import RunContext
from backend.mcp.bridge import sdk_tool_name
from backend.persistence.database import Database
from backend.services.bookings import BookingService
from backend.services.travel import TravelService
from mock_supplier.app import create_app
from mock_supplier.service import SupplierService
from tests.integration.http_helper import serve_http
from tests.integration.sdk_helper import run_database_worker
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_sdk_cli_offline import scripted_response

pytestmark = pytest.mark.integration


def hold_response(body: bytes) -> tuple[int, bytes]:
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
                (sdk_tool_name("search_hotel_offers"), {"expected_revision": 1, "limit": 1}),
            ),
        )
        return status, response.replace(b"tool_0", b"tool_search")
    if len(results) == 1:
        content = results[0]
        payload = json.loads(content if isinstance(content, str) else content[0]["text"])
        return scripted_response(
            json.dumps({**request, "messages": []}).encode(),
            tool_calls=(
                (
                    sdk_tool_name("hold_hotel"),
                    {"expected_revision": 1, "offer_id": payload["data"]["offers"][0]["offer_id"]},
                ),
            ),
        )
    return scripted_response(body)


@pytest.mark.skipif(not shutil.which("claude"), reason="需要本机Claude CLI，不访问真实模型")
def test_sdk_holds_without_confirming_or_ordering(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
) -> None:
    runner, travel, context = travel_setup
    with serve_http(create_app(Database(travel.database.engine.url))) as url:
        report, guard = run_database_worker(
            travel,
            context,
            tmp_path,
            hold_response,
            "暂留第一间酒店，等待我在页面确认",
            supplier_url=url,
        )
    assert report["status"] == "success", (report.get("code"), guard.failures)
    assert guard.attempts == 3 and not guard.failures
    events = report["events"]
    assert isinstance(events, list)
    assert [e["tool_name"] for e in events if e["kind"] == "tool_finished"] == [
        "search_hotel_offers",
        "hold_hotel",
    ]

    async def check() -> None:
        bookings = await BookingService(travel, SupplierService(travel.database)).list(context)
        assert len(bookings) == 1 and bookings[0].status == "held"
        assert (await SupplierService(travel.database).lookup(bookings[0].client_ref)).order is None

    runner.run(check())

"""原生SDK/CLI与真实PG选择卡往返；模型响应是本地合成SSE。"""

import asyncio
import json
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from backend.domain.execution import RunContext
from backend.mcp.bridge import sdk_tool_name
from backend.persistence import runs
from backend.services.common import transaction
from backend.services.travel import TravelService
from tests.integration.sdk_helper import run_database_worker
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_sdk_cli_offline import scripted_response

pytestmark = pytest.mark.integration


def test_native_sdk_receives_closed_hotel_choice_and_attempt_facts(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], tmp_path: Path
) -> None:
    runner, travel, original = travel_setup

    async def prepare() -> RunContext:
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, original.user_id, original.session_id, uuid4(), "比较酒店", "offline"
            )
            return RunContext(original.user_id, original.session_id, row.id)

    received: list[dict[str, object]] = []
    calls: tuple[tuple[str, dict[str, object]], ...] = (
        (sdk_tool_name("search_hotel_offers"), {"expected_revision": 1}),
    )

    def forward(body: bytes) -> tuple[int, bytes]:
        received.append(json.loads(body))
        return scripted_response(body, tool_calls=calls)

    report, guard = run_database_worker(
        travel, runner.run(prepare()), tmp_path, forward, "比较酒店"
    )
    assert report["status"] == "success" and guard.failures == []
    contents: list[object] = []
    for request in received:
        messages = TypeAdapter(list[dict[str, object]]).validate_python(request["messages"])
        for message in messages:
            parts = message["content"]
            if isinstance(parts, list):
                contents.extend(
                    part["content"]
                    for part in parts
                    if isinstance(part, dict) and part.get("type") == "tool_result"
                )
    assert contents
    serialized = json.dumps(contents, ensure_ascii=False)
    assert "choice_card" in serialized and "auto_retried" in serialized and "attempts" in serialized


def test_native_sdk_roundtrips_server_owned_pace_card(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
) -> None:
    runner, travel, original = travel_setup

    async def prepare() -> RunContext:
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, original.user_id, original.session_id, uuid4(), "合成节奏选择", "offline"
            )
            return RunContext(original.user_id, original.session_id, row.id)

    context = runner.run(prepare())
    calls = (
        (
            sdk_tool_name("update_conversation_state"),
            {"expected_revision": 1, "goals": ["itinerary"], "awaiting_field": "pace"},
        ),
        (
            sdk_tool_name("present_travel_result"),
            {"component": "choice", "kind": "pace", "expected_revision": 1},
        ),
    )
    report, guard = run_database_worker(
        travel, context, tmp_path, partial(scripted_response, tool_calls=calls), "请选择旅行节奏"
    )
    assert report["status"] == "success", (report.get("code"), guard.failures)
    assert guard.attempts == 2 and guard.failures == []
    events = report["events"]
    assert isinstance(events, list)
    choices = [
        event["presentation"]["data"]
        for event in events
        if isinstance(event, dict) and event.get("kind") == "presentation"
    ]
    assert len(choices) == 2 and choices[0]["choice_id"] == choices[1]["choice_id"]
    assert [option["label"] for option in choices[0]["options"]] == ["标准", "特种兵", "比较轻松"]

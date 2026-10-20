"""原生SDK/CLI向PG提出多条记忆；工具呈现不授予确认权限。"""

import asyncio
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext
from backend.mcp.bridge import sdk_tool_name
from backend.persistence import runs
from backend.services.common import transaction
from backend.services.memory import MemoryService
from backend.services.travel import TravelService
from tests.integration.sdk_helper import run_database_worker
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_sdk_cli_offline import scripted_response

pytestmark = pytest.mark.integration


def test_native_sdk_proposes_two_confirmable_facts_without_activating_them(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], tmp_path: Path
) -> None:
    runner, travel, original = travel_setup
    prompt = "我喜欢特种兵式旅行，常用公共交通。"

    async def prepare() -> RunContext:
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, original.user_id, original.session_id, uuid4(), prompt, "offline"
            )
            return RunContext(original.user_id, original.session_id, row.id)

    context = runner.run(prepare())
    calls: tuple[tuple[str, dict[str, object]], ...] = (
        (
            sdk_tool_name("propose_memory"),
            {
                "ops": [
                    {"op": "ADD", "key": "pace", "value": "特种兵", "quote": "我喜欢特种兵式旅行"},
                    {"op": "ADD", "key": "transport", "value": "transit", "quote": "常用公共交通"},
                ]
            },
        ),
    )
    report, guard = run_database_worker(
        travel, context, tmp_path, partial(scripted_response, tool_calls=calls), prompt
    )
    assert report["status"] == "success", (report.get("code"), guard.failures)
    assert guard.failures == []
    events = report["events"]
    assert isinstance(events, list)
    cards = [
        e["presentation"]["data"]
        for e in events
        if isinstance(e, dict) and e.get("kind") == "presentation"
    ]
    assert len(cards) == 2 and all(c["kind"] == "memory_confirm" for c in cards)
    assert runner.run(MemoryService(travel.database).snapshot(context)) == []
    facts = runner.run(MemoryService(travel.database).facts(context.user_id))
    assert len(facts) == 2 and all(f.status == "proposed" for f in facts)

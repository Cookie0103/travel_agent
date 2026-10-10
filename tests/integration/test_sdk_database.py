"""R01/R03：真实SDK/CLI使用数据库旅行工具；模型响应由本地HTTP脚本提供。"""

import asyncio
import shutil
from functools import partial
from pathlib import Path

import pytest

from backend.domain.execution import RunContext
from backend.mcp.bridge import sdk_tool_name
from backend.persistence.catalog import import_catalog
from backend.services.common import transaction
from backend.services.travel import TravelService
from data.import_catalog import load_snapshot
from tests.integration.sdk_helper import run_database_worker
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_sdk_cli_offline import scripted_response

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not shutil.which("claude"), reason="需要本机Claude CLI，不访问真实模型")
def test_native_sdk_reads_snapshot_and_updates_database_conditions(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], tmp_path: Path
) -> None:
    runner, travel, context = travel_setup

    async def prepare() -> None:
        async with transaction(travel.database) as db:
            await import_catalog(db, load_snapshot())

    runner.run(prepare())
    calls = (
        (sdk_tool_name("search_places"), {"city": "京都", "query": "二条", "limit": 1}),
        (
            sdk_tool_name("update_travel_request"),
            {"expected_revision": 1, "set": {"rooms": 2}, "explicit_fields": ["rooms"]},
        ),
    )
    report, guard = run_database_worker(
        travel,
        context,
        tmp_path,
        partial(scripted_response, tool_calls=calls),
        "查询二条城，并把房间数改为2",
    )
    assert report["status"] == "success", (report.get("code"), guard.failures)
    assert guard.attempts == 2 and not guard.failures
    request = runner.run(travel.get_request(context))
    assert request.revision == 2 and request.rooms == 2
    results = report["results"]
    assert isinstance(results, list) and len(results) == 1
    assert "snapshot" in results[0]["outcome"]["text"]
    assert "evidence_id" in results[0]["outcome"]["text"]

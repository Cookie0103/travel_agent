"""R01/R03：真实SDK/CLI使用数据库旅行工具；模型响应由本地HTTP脚本提供。"""

import asyncio
import os
import shutil
from decimal import Decimal
from functools import partial
from pathlib import Path

import pytest

from backend.domain.execution import RunContext
from backend.mcp.bridge import sdk_tool_name
from backend.persistence.catalog import import_catalog
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import find_cli, worker_environment
from backend.providers.claude_agent.guard import Guard, serve
from backend.providers.claude_agent.process import invoke_worker, run_process
from backend.providers.probe.settings import Settings
from backend.services.common import transaction
from backend.services.travel import TravelService
from backend.tools.travel import DEFINITIONS
from data.import_catalog import load_snapshot
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
        (sdk_tool_name("update_travel_request"), {"expected_revision": 1, "set": {"rooms": 2}}),
    )
    guard = Guard(
        Settings("offline-only", "deepseek-flash", Decimal(5), Decimal(0)),
        Budget(tmp_path / "ledger", tmp_path / "old", Decimal(5)),
        partial(scripted_response, tool_calls=calls),
        allowed_tools=frozenset(sdk_tool_name(d.name) for d in DEFINITIONS),
    )
    root = Path(__file__).resolve().parents[2]
    with serve(guard) as endpoint:
        directory = tmp_path / "worker"
        cli = find_cli(os.environ)
        env = worker_environment(
            os.environ, directory, root, endpoint, guard.token, "deepseek-flash"
        )
        version = run_process([str(cli), "--version"], directory, env, timeout=10)
        report = invoke_worker(
            cli,
            directory,
            env,
            module="backend.providers.claude_agent.worker",
            payload={
                "prompts": ["查询二条城，并把房间数改为2"],
                "user_id": str(context.user_id),
                "session_id": str(context.session_id),
                "run_id": str(context.run_id),
                "cli_version": version.stdout.split()[0],
                "database_dsn": travel.database.engine.url.render_as_string(hide_password=False),
            },
        )
    assert report["status"] == "success", (report.get("code"), guard.failures)
    assert guard.attempts == 2 and not guard.failures
    request = runner.run(travel.get_request(context))
    assert request.revision == 2 and request.rooms == 2
    results = report["results"]
    assert isinstance(results, list) and len(results) == 1
    assert "snapshot" in results[0]["outcome"]["text"]
    assert "evidence_id" in results[0]["outcome"]["text"]

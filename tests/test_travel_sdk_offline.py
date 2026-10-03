"""R01/R02：真实 SDK/CLI 调用两个旅行工具并续接；全部 API 响应来自本地脚本。"""

import os
import shutil
from decimal import Decimal
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest

from backend.mcp.bridge import sdk_tool_name
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import find_cli, worker_environment
from backend.providers.claude_agent.guard import Guard, serve
from backend.providers.claude_agent.process import invoke_worker, run_process
from backend.providers.probe.settings import Settings
from backend.tools.search import DEFINITIONS
from tests.test_sdk_cli_offline import scripted_response


@pytest.mark.skipif(not shutil.which("claude"), reason="需要本机 Claude CLI；不调用真实模型")
def test_sdk_executes_travel_tools_and_resumes_same_session(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    calls = tuple(
        (sdk_tool_name(d.name), {"city": "京都", "query": "室内", "limit": 2}) for d in DEFINITIONS
    )
    guard = Guard(
        Settings("offline-token", "deepseek-flash", Decimal(5), Decimal(0)),
        Budget(tmp_path / "ledger", tmp_path / "old", Decimal(5)),
        partial(scripted_response, tool_calls=calls),
        allowed_tools=frozenset(name for name, _ in calls),
    )
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
                "prompts": ["京都室内景点", "请复述已有结果"],
                "user_id": str(uuid4()),
                "session_id": str(uuid4()),
                "cli_version": version.stdout.split()[0],
            },
        )
    assert report["status"] == "success", (report, guard.failures)
    results, events = report["results"], report["events"]
    assert isinstance(results, list) and len(results) == 2
    assert results[0]["reference"]["sdk_session_id"] == results[1]["reference"]["sdk_session_id"]
    assert "fixture:kyoto-v1" in results[0]["outcome"]["text"]
    assert "fixture:kyoto-guide-v1" in results[0]["outcome"]["text"]
    assert isinstance(events, list)
    assert {e["tool_name"] for e in events if e["kind"] == "tool_finished"} == {
        "search_places",
        "search_content",
    }
    assert guard.attempts == 3 and not guard.failures

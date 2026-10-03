"""数据库工具的真实SDK离线测试共用启动器；私有连接串只交给自有worker stdin。"""

import os
from decimal import Decimal
from pathlib import Path

from backend.domain.execution import RunContext
from backend.mcp.bridge import sdk_tool_name
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import find_cli, worker_environment
from backend.providers.claude_agent.guard import Forward, Guard, serve
from backend.providers.claude_agent.process import invoke_worker, run_process
from backend.providers.probe.settings import Settings
from backend.services.travel import TravelService
from backend.tools.travel import DEFINITIONS


def run_database_worker(
    travel: TravelService,
    context: RunContext,
    directory: Path,
    forward: Forward,
    prompt: str,
) -> tuple[dict[str, object], Guard]:
    guard = Guard(
        Settings("offline-only", "deepseek-flash", Decimal(5), Decimal(0)),
        Budget(directory / "ledger", directory / "old", Decimal(5)),
        forward,
        allowed_tools=frozenset(sdk_tool_name(d.name) for d in DEFINITIONS),
    )
    with serve(guard) as endpoint:
        cli = find_cli(os.environ)
        worker = directory / "worker"
        env = worker_environment(
            os.environ,
            worker,
            Path(__file__).resolve().parents[2],
            endpoint,
            guard.token,
            "deepseek-flash",
        )
        version = run_process([str(cli), "--version"], worker, env, timeout=10)
        report = invoke_worker(
            cli,
            worker,
            env,
            module="backend.providers.claude_agent.worker",
            payload={
                "prompts": [prompt],
                "user_id": str(context.user_id),
                "session_id": str(context.session_id),
                "run_id": str(context.run_id),
                "cli_version": version.stdout.split()[0],
                "database_dsn": travel.database.engine.url.render_as_string(hide_password=False),
            },
        )
    return report, guard

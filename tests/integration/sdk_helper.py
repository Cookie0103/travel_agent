"""数据库工具的真实SDK离线测试共用启动器；私有连接串只交给自有worker stdin。"""

import os
from decimal import Decimal
from pathlib import Path

from backend.domain.execution import RunContext
from backend.mcp.bridge import sdk_tool_name
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import find_cli, worker_environment
from backend.providers.claude_agent.evaluation import EvaluationVariant, evaluation_definitions
from backend.providers.claude_agent.guard import Forward, Guard, serve
from backend.providers.claude_agent.process import invoke_worker, run_process
from backend.providers.probe.settings import Settings
from backend.services.travel import TravelService
from backend.tools.workflow import WorkflowName


def run_database_worker(
    travel: TravelService,
    context: RunContext,
    directory: Path,
    forward: Forward,
    prompt: str,
    *,
    max_attempts: int = 4,
    supplier_url: str | None = None,
    auto_compact_percent: int | None = None,
    prompts: list[str] | None = None,
    workflow: WorkflowName | None = None,
    variant: EvaluationVariant = "full",
) -> tuple[dict[str, object], Guard]:
    guard = Guard(
        Settings("offline-only", "deepseek-flash", Decimal(5), Decimal(0)),
        Budget(directory / "ledger", directory / "old", Decimal(5)),
        forward,
        allowed_tools=frozenset(
            sdk_tool_name(d.name) for d in evaluation_definitions(variant, database=True)
        ),
        max_attempts=max_attempts,
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
        if auto_compact_percent is not None:
            env["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] = str(auto_compact_percent)
        version = run_process([str(cli), "--version"], worker, env, timeout=10)
        report = invoke_worker(
            cli,
            worker,
            env,
            module="backend.providers.claude_agent.worker",
            payload={
                "prompts": prompts if prompts is not None else [prompt],
                "user_id": str(context.user_id),
                "session_id": str(context.session_id),
                "run_id": str(context.run_id),
                "cli_version": version.stdout.split()[0],
                "database_dsn": travel.database.engine.url.render_as_string(hide_password=False),
                "supplier_url": supplier_url,
                "workflow": workflow,
                "evaluation_variant": variant,
            },
        )
    return report, guard

"""数据库工具的真实SDK离线测试共用启动器；私有连接串只交给自有worker stdin。"""

import os
from decimal import Decimal
from pathlib import Path

from backend.domain.execution import RunContext
from backend.limits import Settings
from backend.mcp.bridge import sdk_tool_name
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import find_cli, worker_environment
from backend.providers.claude_agent.evaluation import EvaluationVariant, evaluation_definitions
from backend.providers.claude_agent.guard import Forward, Guard, serve
from backend.providers.claude_agent.process import invoke_worker, run_process
from backend.services.travel import TravelService
from backend.tools.workflow import WorkflowName


def inflate_usage(response: bytes, body: bytes) -> bytes:
    """把假上游的input_tokens抬高到足以触发SDK压缩阈值，但不超过守卫的预占上界。

    预占按请求体字节*1.25+1024个token计价(request.py)；真实上游用量不会超过它，
    超过则守卫按设计失败关闭。故人工usage取上界再留200token余量(含输出计价)，而不是固定4万。
    """
    tokens = len(body) * 5 // 4 + 1024 - 200
    return response.replace(b'"input_tokens": 100', f'"input_tokens": {tokens}'.encode())


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

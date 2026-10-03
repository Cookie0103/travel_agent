"""显式 live 的组合入口；复用已验证的请求预算、环境隔离和进程期限。"""

import json
import os
from functools import partial
from pathlib import Path

from backend.adapters.tracing import cloud_exporter, trace_report
from backend.domain.execution import RunContext
from backend.mcp.bridge import sdk_tool_name
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import find_cli, worker_environment
from backend.providers.claude_agent.guard import Guard, serve
from backend.providers.claude_agent.http import forward_deepseek
from backend.providers.claude_agent.process import invoke_worker, run_process
from backend.providers.probe.ledger import exclusive
from backend.providers.probe.settings import ProbeError, load_settings
from backend.tools.search import DEFINITIONS


def run_live(
    prompt: str, context: RunContext, root: Path, *, trace_cloud: bool = False
) -> dict[str, object]:
    exporter = cloud_exporter(os.environ) if trace_cloud else None
    settings = load_settings(os.environ)
    cli = find_cli(os.environ)
    cache = root / ".cache"
    directory = cache / "sessions" / str(context.user_id) / str(context.session_id)
    budget = Budget(
        cache / "model-budget" / "deepseek.jsonl",
        cache / "m02-protocol" / "ledger.jsonl",
        settings.cny_limit,
    )
    with exclusive(cache / "model-budget" / "active.lock"):
        _, before_charge = budget.totals()
        guard = Guard(
            settings,
            budget,
            partial(forward_deepseek, settings.api_key),
            allowed_tools=frozenset(sdk_tool_name(d.name) for d in DEFINITIONS),
        )
        with serve(guard) as endpoint:
            env = worker_environment(
                os.environ, directory, root, endpoint, guard.token, settings.model
            )
            version = run_process([str(cli), "--version"], directory, env, timeout=10)
            if version.returncode:
                raise ProbeError("unavailable", "Claude CLI 版本检查失败")
            report = invoke_worker(
                cli,
                directory,
                env,
                module="backend.providers.claude_agent.worker",
                payload={
                    "prompts": [prompt],
                    "user_id": str(context.user_id),
                    "session_id": str(context.session_id),
                    "cli_version": version.stdout.split()[0],
                },
            )
        count, charge = budget.totals()
        report.update(
            http_attempts=guard.attempts,
            requests=guard.observations,
            grant_attempts=count,
            grant_accounted_cny=str(charge),
            run_accounted_cny=str(charge - before_charge),
            guard_failures=guard.failures,
        )
        if guard.failures:
            report["status"] = "error"
        if guard.observations and guard.observations[-1]["stop_reason"] not in {
            "end_turn",
            "stop_sequence",
        }:
            # 旧 CLI 可能没有向 SDK 透出 stop_reason；费用仍按完整 usage 结算。
            report.update(status="error", code="provider_error", reason="incomplete_output")
        # 先保存执行证据，即使随后进程在导出期间被终止也能恢复结果。
        (directory / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        trace_report(report, directory, exporter)
        (directory / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        return report

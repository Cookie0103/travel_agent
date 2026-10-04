"""实测入口编排本地守卫与 SDK 工作进程；不直接调用模型 Messages SDK。"""

import importlib.metadata
import json
import os
from functools import partial
from pathlib import Path

from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import find_cli, worker_environment
from backend.providers.claude_agent.guard import Guard, serve
from backend.providers.claude_agent.http import forward_deepseek
from backend.providers.claude_agent.process import invoke_worker, run_process
from backend.providers.probe.ledger import exclusive
from backend.providers.probe.settings import Settings


def run_probe(settings: Settings, root: Path) -> dict[str, object]:
    """仅由显式 live 测试调用；累积账本不随某次实验目录改变。"""
    cache = root / ".cache"
    directory = cache / "sdk-probe"
    budget = Budget(
        cache / "model-budget" / "deepseek.jsonl",
        cache / "m02-protocol" / "ledger.jsonl",
        settings.cny_limit,
    )
    cli = find_cli(os.environ)
    with exclusive(cache / "model-budget" / "active.lock"):
        guard = Guard(settings, budget, partial(forward_deepseek, settings.api_key))
        with serve(guard) as endpoint:
            env = worker_environment(
                os.environ, directory, root, endpoint, guard.token, settings.model
            )
            report = invoke_worker(cli, directory, env)
            version = run_process([str(cli), "--version"], directory, env, timeout=10)
            report["cli_version"] = version.stdout.strip() if version.returncode == 0 else "unknown"
        count, charge = budget.totals()
        report.update(
            {
                "sdk": importlib.metadata.version("claude-agent-sdk"),
                "mcp": importlib.metadata.version("mcp"),
                "http_attempts": guard.attempts,
                "requests": guard.observations,
                "guard_failures": guard.failures,
                "failure_details": guard.failure_details,
                "grant_attempts": count,
                "grant_accounted_cny": str(charge),
            }
        )
        if guard.failures:
            report["status"] = "error"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        return report

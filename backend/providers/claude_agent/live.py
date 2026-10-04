"""显式 live 的组合入口；复用已验证的请求预算、环境隔离和进程期限。"""

import json
import os
from functools import partial
from pathlib import Path
from threading import Event

from backend.adapters.tracing import cloud_exporter, trace_report
from backend.agent.persona import JudgeKind
from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeEvent, error_code
from backend.mcp.bridge import sdk_tool_name
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import find_cli, worker_environment
from backend.providers.claude_agent.evaluation import (
    EvaluationVariant,
    evaluation_definitions,
    validate_variant,
)
from backend.providers.claude_agent.events import EventReader
from backend.providers.claude_agent.guard import Guard, serve
from backend.providers.claude_agent.http import forward_deepseek, forward_messages
from backend.providers.claude_agent.process import invoke_worker, run_process
from backend.providers.claude_agent.settings import load_runtime_settings
from backend.providers.probe.ledger import exclusive
from backend.providers.probe.settings import ProbeError, Provider, Settings
from backend.tools.workflow import WorkflowName


def runtime_budget(root: Path, settings: Settings) -> Budget:
    cache = root / ".cache"
    return Budget(
        cache / "model-budget" / f"{settings.provider}.jsonl",
        cache / "m02-protocol" / "ledger.jsonl",
        settings.daily_limit,
        settings.currency,
    )


def check_evaluation_size(root: Path, minimum_requests: int) -> None:
    runtime_budget(root, load_runtime_settings(os.environ)).check_minimum_requests(minimum_requests)


def run_live(
    prompt: str,
    context: RunContext,
    root: Path,
    *,
    trace_cloud: bool = False,
    database_dsn: str | None = None,
    emit: EventSink | None = None,
    cancelled: Event | None = None,
    workflow: WorkflowName | None = None,
    max_attempts: int = 4,
    supplier_url: str | None = None,
    persona_judge: bool = False,
    judge_kind: JudgeKind = "persona",
    evaluation_variant: EvaluationVariant = "full",
    provider: Provider | None = None,
) -> dict[str, object]:
    try:
        validate_variant(
            evaluation_variant,
            database=database_dsn is not None,
            workflow=workflow,
            judge=persona_judge,
        )
    except ValueError as error:
        raise ProbeError("validation", str(error)) from None
    if (
        judge_kind not in ("persona", "content")
        or (judge_kind != "persona" and not persona_judge)
        or type(max_attempts) is not int
        or not 1 <= max_attempts <= 12
        or (workflow is not None and database_dsn is None)
        or type(persona_judge) is not bool
        or (persona_judge and any((database_dsn, supplier_url, workflow)))
    ):
        raise ProbeError("validation", "对照需数据库工具；请求上限须为1至12")
    exporter = cloud_exporter(os.environ) if trace_cloud else None
    settings = load_runtime_settings(
        {**os.environ, "LLM_PROVIDER": provider} if provider is not None else os.environ
    )
    if persona_judge and settings.provider != "deepseek":
        raise ProbeError("blocked", "语气评审仅核验了DeepSeek固定温度线路")
    cache = root / ".cache"
    directory = cache / "sessions" / str(context.user_id) / str(context.session_id)
    event_path = directory / f"events-{context.run_id}.jsonl"
    reader = EventReader(event_path, context, emit)
    definitions = (
        ()
        if persona_judge
        else evaluation_definitions(evaluation_variant, database=database_dsn is not None)
    )
    budget = runtime_budget(root, settings)
    budget.check_authorization()
    cli = find_cli(os.environ)
    with exclusive(cache / "model-budget" / "active.lock"):
        if event_path.exists():
            raise ProbeError("conflict", "此run已有执行记录，不能自动重复付费执行")
        _, before_charge = budget.totals()
        guard = Guard(
            settings,
            budget,
            partial(forward_deepseek, settings.api_key)
            if settings.provider == "deepseek"
            else partial(forward_messages, settings.provider, settings.api_key),
            allowed_tools=frozenset(sdk_tool_name(d.name) for d in definitions),
            max_attempts=max_attempts,
        )
        if persona_judge:
            guard.temperature = 0
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
                    "run_id": str(context.run_id),
                    "database_dsn": database_dsn,
                    "supplier_url": None
                    if persona_judge or evaluation_variant == "no_tools"
                    else supplier_url or os.environ.get("MOCK_SUPPLIER_URL"),
                    "cli_version": version.stdout.split()[0],
                    "workflow": workflow,
                    "provider": settings.provider,
                    "persona_judge": persona_judge,
                    "judge_kind": judge_kind,
                    "evaluation_variant": evaluation_variant,
                },
                cancelled=cancelled,
                progress=reader.drain,
            )
        count, charge = budget.totals()
        report.update(
            http_attempts=guard.attempts,
            requests=guard.observations,
            grant_attempts=count,
            currency=settings.currency,
            grant_accounted=str(charge),
            run_accounted=str(charge - before_charge),
            guard_failures=guard.failures,
            guard_failure_details=guard.failure_details,
        )
        if settings.currency == "CNY":
            report.update(
                grant_accounted_cny=str(charge), run_accounted_cny=str(charge - before_charge)
            )
        if guard.failures:
            report["status"] = "error"
        if (
            report.get("status") == "success"
            and guard.observations
            and guard.observations[-1]["stop_reason"]
            not in {
                "end_turn",
                "stop_sequence",
            }
        ):
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
        if emit is not None:
            code = report.get("code")
            if report.get("status") == "success":
                emit(RuntimeEvent(context, "completed"))
            else:
                emit(
                    RuntimeEvent(
                        context,
                        "cancelled" if code == "cancelled" else "failed",
                        code=error_code(code),
                    )
                )
        return report

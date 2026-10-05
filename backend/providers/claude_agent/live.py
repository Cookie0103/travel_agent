"""显式 live 的组合入口；复用已验证的请求预算、环境隔离和进程期限。"""

import json
import os
import time
from functools import partial
from pathlib import Path
from threading import Event

from backend.adapters.tracing import cloud_exporter, trace_report
from backend.agent.persona import JudgeKind
from backend.agent.runtime import EventSink
from backend.domain.execution import (
    UPSTREAM_REASON,
    RunContext,
    RuntimeEvent,
    error_code,
    event_metadata,
)
from backend.mcp.bridge import sdk_tool_name
from backend.providers.claude_agent import http as upstream
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import find_cli, worker_environment
from backend.providers.claude_agent.evaluation import (
    EvaluationVariant,
    evaluation_definitions,
    validate_variant,
)
from backend.providers.claude_agent.events import EventReader
from backend.providers.claude_agent.guard import Guard, serve
from backend.providers.claude_agent.http import forward_messages
from backend.providers.claude_agent.ledger import exclusive
from backend.providers.claude_agent.limits import ProbeError, Provider, Settings
from backend.providers.claude_agent.process import invoke_worker, run_process
from backend.providers.claude_agent.profile import current
from backend.providers.claude_agent.settings import load_runtime_settings
from backend.tools.travel import live_definitions
from backend.tools.workflow import WorkflowName
from backend.trace_log import FILE_ENV, RUN_ENV, Tail, trace


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
    real_data: bool = False,
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
        or not 1 <= max_attempts <= current().max_attempts
        or (workflow is not None and database_dsn is None)
        or type(persona_judge) is not bool
        or (persona_judge and any((database_dsn, supplier_url, workflow)))
    ):
        raise ProbeError("validation", f"对照需数据库工具；请求上限须为1至{current().max_attempts}")
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
    # 子进程（worker/上游转发器）的TRACE写入此文件，父进程每0.2秒转印到自己的stdout。
    trace_path = directory / f"trace-{context.run_id}.jsonl"
    tail, run = Tail(trace_path), str(context.run_id)

    def drain() -> None:
        tail.drain()
        reader.drain()

    definitions = (
        ()
        if persona_judge
        else evaluation_definitions(evaluation_variant, database=database_dsn is not None)
    )
    if real_data:
        definitions = live_definitions(definitions)
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
            partial(forward_messages, settings.provider, settings.api_key),
            allowed_tools=frozenset(sdk_tool_name(d.name) for d in definitions),
            max_attempts=max_attempts,
        )
        guard.run = run[:8]
        upstream.child_trace = (trace_path, run[:8])  # 每个run开始时覆盖；独占锁保证一次一个
        if persona_judge:
            guard.temperature = 0
        with serve(guard) as endpoint:
            env = worker_environment(
                os.environ, directory, root, endpoint, guard.token, settings.model
            )
            env.update({FILE_ENV: str(trace_path), RUN_ENV: run[:8]})
            version = run_process([str(cli), "--version"], directory, env, timeout=10)
            if version.returncode:
                raise ProbeError("unavailable", "Claude CLI 版本检查失败")
            trace("worker_spawned", run, provider=settings.provider, real_data=real_data)
            worker_started = time.monotonic()
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
                    "real_data": real_data,
                },
                cancelled=cancelled,
                progress=drain,
            )
            tail.drain()  # 超时/被杀时也要转印已写出的子进程TRACE
            trace(
                "worker_exited",
                run,
                status=report.get("status"),
                code=report.get("code"),
                reason=report.get("reason"),
                exit_code=report.get("exit_code"),
                elapsed_ms=round((time.monotonic() - worker_started) * 1000),
                http_attempts=guard.attempts,
                guard_failures=guard.failures,
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
            if "timeout" in guard.failures and report.get("code") != "cancelled":
                trace(
                    "timeout_fired",
                    run,
                    layer="upstream",
                    limit_s=current().upstream_timeout,
                    elapsed_ms=round((time.monotonic() - worker_started) * 1000),
                    guard_failures=guard.failures,
                )
                report.update(code="timeout", reason="upstream_timeout")
            elif guard.upstream_status is not None and report.get("code") != "cancelled":
                # 供应商HTTP错误(402/401/429/5xx…)：仅传状态码，UI据此显示固定说明。
                report.update(
                    reason=f"{UPSTREAM_REASON}{guard.upstream_status}",
                    upstream_http_status=guard.upstream_status,
                )
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
            trace("incomplete_output", run, stop_reason=guard.observations[-1]["stop_reason"])
            report.update(status="error", code="provider_error", reason="incomplete_output")
        # 先保存执行证据，即使随后进程在导出期间被终止也能恢复结果。
        stored = report_metadata_only(report) if real_data else report
        if real_data and event_path.exists():
            stored_events = stored.get("events", [])
            assert isinstance(stored_events, list)
            event_path.write_text(
                "".join(
                    json.dumps(event, ensure_ascii=False, default=str) + "\n"
                    for event in stored_events
                    if isinstance(event, dict)
                ),
                encoding="utf-8",
                newline="\n",
            )
        (directory / "report.json").write_text(
            json.dumps(stored, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        trace_report(stored, directory, exporter)
        (directory / "report.json").write_text(
            json.dumps(stored, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
            newline="\n",
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


def report_metadata_only(report: dict[str, object]) -> dict[str, object]:
    from dataclasses import asdict

    from pydantic import TypeAdapter

    safe = dict(report)
    events = TypeAdapter(list[RuntimeEvent]).validate_python(report.get("events", []))
    safe["events"] = [asdict(event_metadata(event)) for event in events]
    results = report.get("results")
    if isinstance(results, list):
        safe["results"] = [
            {**result, "outcome": {**result["outcome"], "text": ""}}
            for result in results
            if isinstance(result, dict) and isinstance(result.get("outcome"), dict)
        ]
    return safe

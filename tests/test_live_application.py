"""父进程与应用边界的故障回归；全部替换工作进程，不访问收费模型。"""

import asyncio
import subprocess
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RunResult, RuntimeEvent, RuntimeOutcome, error_code
from backend.providers.claude_agent import application, live
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.events import save_event
from backend.providers.claude_agent.guard import Forward, Guard
from backend.providers.claude_agent.limits import ProbeError, Settings


@pytest.mark.parametrize("failure", ["cancelled", "worker_exit", "guard_failure"])
def test_parent_failure_never_publishes_worker_completed(
    failure: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = RunContext(uuid4())
    emitted: list[RuntimeEvent] = []
    guards: list[Guard] = []

    def guard(
        settings: Settings,
        budget: Budget,
        forward: Forward,
        *,
        allowed_tools: frozenset[str],
        max_attempts: int = 4,
    ) -> Guard:
        created = Guard(
            settings, budget, forward, allowed_tools=allowed_tools, max_attempts=max_attempts
        )
        guards.append(created)
        return created

    def worker(*args: object, **kwargs: object) -> dict[str, object]:
        directory = (
            tmp_path / ".cache" / "sessions" / str(context.user_id) / str(context.session_id)
        )
        save_event(directory / f"events-{context.run_id}.jsonl", RuntimeEvent(context, "completed"))
        progress = kwargs["progress"]
        assert callable(progress)
        progress()
        assert not emitted
        guards[0].observations.append({"stop_reason": "tool_use"})
        if failure == "guard_failure":
            guards[0].failures.append("blocked")
            return {"status": "success"}
        return {"status": "error", "code": failure}

    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-only")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    monkeypatch.setenv("DAILY_BUDGET_CNY", "5")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0")
    monkeypatch.setattr(live, "find_cli", lambda environment: tmp_path / "offline-cli")
    monkeypatch.setattr(
        live, "run_process", lambda *a, **k: subprocess.CompletedProcess([], 0, "2.1.114", "")
    )
    monkeypatch.setattr(live, "invoke_worker", worker)
    monkeypatch.setattr(live, "Guard", guard)
    monkeypatch.setattr(live, "trace_report", lambda *a, **k: None)
    report = live.run_live("offline", context, tmp_path, emit=emitted.append)
    assert report["status"] == "error" and len(emitted) == 1
    assert emitted[0].kind == ("cancelled" if failure == "cancelled" else "failed")
    if failure == "cancelled":
        assert report["code"] == "cancelled"
        assert emitted[0].code == "cancelled"
    with pytest.raises(ProbeError, match="conflict"):
        live.run_live("offline", context, tmp_path)


def test_application_rejects_cross_run_report() -> None:
    context = RunContext(uuid4())
    result = RunResult(
        RunContext(context.user_id, context.session_id), RuntimeOutcome(sdk_session_id="sdk")
    )
    report: dict[str, object] = {"status": "success", "results": [asdict(result)]}
    assert application.outcome(report, context).code == "blocked"


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "missing",
        "cross_run",
        "cross_result",
        "provider",
        "model",
        "sdk",
        "attempts",
        "amount",
    ],
)
def test_application_retains_only_bound_trace_metadata_without_changing_result(
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R17：报告错误保持用量未知，不传播正文/连接串或修改运行身份。"""
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    context = RunContext(uuid4())
    runtime = application.GuardedRuntime(tmp_path, "synthetic-private-dsn")
    initial = runtime.identity
    actual = replace(initial, cli_version="2.1.114")
    report: dict[str, object] = {
        "status": "success",
        "results": [asdict(RunResult(context, RuntimeOutcome(text="private-answer")))],
        "identity": asdict(actual),
        "events": [asdict(RuntimeEvent(context, "completed"))],
        "http_attempts": 2,
        "currency": "CNY",
        "run_accounted_cny": "0.02",
        "requests": [{"input_tokens": 7, "output_tokens": 2, "usage_cost_upper_cny": "0.01"}],
    }
    if mutation == "missing":
        report.pop("events")
    elif mutation == "cross_run":
        report["events"] = [asdict(RuntimeEvent(RunContext(uuid4()), "completed"))]
    elif mutation == "cross_result":
        report["results"] = [asdict(RunResult(RunContext(uuid4()), RuntimeOutcome()))]
    elif mutation in {"provider", "model", "sdk"}:
        identity = asdict(actual)
        identity["sdk_version" if mutation == "sdk" else mutation] = "synthetic-private-invalid"
        report["identity"] = identity
    elif mutation == "attempts":
        report["http_attempts"] = True
    elif mutation == "amount":
        report["run_accounted_cny"] = "NaN"
    monkeypatch.setattr(application, "run_live", lambda *a, **kw: report)

    async def exercise() -> None:
        result = await runtime.execute(
            context, "private-prompt", None, lambda e: None, asyncio.Event()
        )
        assert (result.code == "blocked") == (mutation == "cross_result")
        assert runtime.identity is initial
        if mutation == "none":
            assert runtime.trace_metadata is not None
            assert runtime.trace_metadata.identity == actual
            assert runtime.trace_metadata.http_attempts == 2
            assert runtime.trace_metadata.accounted == Decimal("0.02")
        else:
            assert runtime.trace_metadata is None
            assert "SDK Trace metadata unavailable" in caplog.text
        assert all(
            s not in caplog.text
            for s in [
                "private-prompt",
                "private-answer",
                "synthetic-private-dsn",
                "synthetic-private-invalid",
            ]
        )
        # 重用时先清空，早期拒绝不能留下上一轮用量。
        await runtime.execute(
            context, "private-prompt", "unsupported-resume", lambda e: None, asyncio.Event()
        )
        assert runtime.trace_metadata is None

    asyncio.run(exercise())


def test_cancelled_application_retains_settled_usage_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """R17：取消仍计费，清理完成的同轮报告不能被丢弃。"""
    from threading import Event

    started, cleaned = Event(), Event()
    context = RunContext(uuid4())
    runtime = application.GuardedRuntime(tmp_path, "offline-dsn")

    def operation(*args: object, **kwargs: object) -> dict[str, object]:
        stop = kwargs["cancelled"]
        assert isinstance(stop, Event)
        started.set()
        assert stop.wait(2)
        cleaned.set()
        return {
            "status": "error",
            "code": "cancelled",
            "identity": asdict(runtime.identity),
            "events": [asdict(RuntimeEvent(context, "cancelled"))],
            "http_attempts": 1,
            "requests": [],
            "run_accounted_cny": "0.02",
        }

    monkeypatch.setattr(application, "run_live", operation)

    async def exercise() -> None:
        task = asyncio.create_task(
            runtime.execute(context, "test", None, lambda e: None, asyncio.Event())
        )
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        assert (await task).code == "cancelled" and cleaned.is_set()
        assert runtime.trace_metadata is not None
        assert runtime.trace_metadata.http_attempts == 1
        assert runtime.trace_metadata.accounted == Decimal("0.02")

    asyncio.run(exercise())


def test_application_business_limit_and_compaction_event_reach_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = RunContext(uuid4())
    forwarded: list[RuntimeEvent] = []

    def operation(*args: object, **kwargs: object) -> dict[str, object]:
        assert kwargs["max_attempts"] == 12
        emit = kwargs["emit"]
        assert callable(emit)
        for kind in ("started", "context_compacted", "completed"):
            emit(RuntimeEvent(context, TypeAdapter(EventKind).validate_python(kind)))
        return {
            "status": "success",
            "results": [asdict(RunResult(context, RuntimeOutcome(text="ok")))],
        }

    from pydantic import TypeAdapter

    from backend.domain.execution import EventKind

    monkeypatch.setattr(application, "run_live", operation)

    async def exercise() -> None:
        runtime = application.GuardedRuntime(tmp_path, "offline-dsn")
        result = await runtime.execute(context, "test", None, forwarded.append, asyncio.Event())
        assert result.code is None
        await asyncio.sleep(0)
        assert [e.kind for e in forwarded] == ["context_compacted"]

    asyncio.run(exercise())


@pytest.mark.parametrize("limit", [0, -1, 13, True])
def test_invalid_request_limit_stops_before_loading_credentials(
    limit: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object) -> Settings:
        raise AssertionError("invalid limit must not reach credentials or model")

    monkeypatch.setattr(live, "load_runtime_settings", forbidden)
    with pytest.raises(ProbeError, match="validation"):
        live.run_live("offline", RunContext(uuid4()), tmp_path, max_attempts=limit)


def test_external_cancel_waits_for_cleanup_even_when_worker_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from threading import Event

    started, cleaned = Event(), Event()

    def operation(*args: object, **kwargs: object) -> dict[str, object]:
        cancelled = kwargs["cancelled"]
        assert isinstance(cancelled, Event)
        started.set()
        assert cancelled.wait(2)
        cleaned.set()
        raise ProbeError("unavailable", "offline cleanup failure")

    monkeypatch.setattr(application, "run_live", operation)

    async def exercise() -> None:
        runtime = application.GuardedRuntime(tmp_path, "private-offline-dsn")
        task = asyncio.create_task(
            runtime.execute(RunContext(uuid4()), "test", None, lambda e: None, asyncio.Event())
        )
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        assert (await task).code == "cancelled"
        assert cleaned.is_set()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "code",
    [
        "validation",
        "blocked",
        "unavailable",
        "timeout",
        "rate_limited",
        "provider_error",
        "conflict",
        "cancelled",
    ],
)
def test_external_error_normalization_preserves_application_codes(code: str) -> None:
    assert error_code(code) == code
    assert error_code("worker_exit") == "provider_error"
    assert error_code(None) == "provider_error"

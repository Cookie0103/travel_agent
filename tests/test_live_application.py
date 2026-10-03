"""父进程与应用边界的故障回归；全部替换工作进程，不访问收费模型。"""

import asyncio
import subprocess
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RunResult, RuntimeEvent, RuntimeOutcome, error_code
from backend.providers.claude_agent import application, live
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.events import save_event
from backend.providers.claude_agent.guard import Forward, Guard
from backend.providers.probe.settings import ProbeError, Settings


@pytest.mark.parametrize("failure", ["cancelled", "worker_exit", "guard_failure"])
def test_parent_failure_never_publishes_worker_completed(
    failure: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = RunContext(uuid4())
    emitted: list[RuntimeEvent] = []
    guards: list[Guard] = []

    def guard(
        settings: Settings, budget: Budget, forward: Forward, *, allowed_tools: frozenset[str]
    ) -> Guard:
        created = Guard(settings, budget, forward, allowed_tools=allowed_tools)
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

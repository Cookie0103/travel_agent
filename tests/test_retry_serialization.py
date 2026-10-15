"""实际worker结果与进程事件入口保留闭合元数据，不把模型对象转成字符串。"""

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from backend.domain.execution import (
    RunContext,
    RunResult,
    RuntimeEvent,
    RuntimeIdentity,
    RuntimeOutcome,
    event_metadata,
)
from backend.domain.external_data import ExternalAttempt
from backend.providers.claude_agent import worker
from backend.providers.claude_agent.application import GuardedRuntime
from backend.providers.claude_agent.events import EventReader, save_event
from tests.test_external_tool_recovery import SyntheticExecutor


def test_worker_result_preserves_external_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = RunContext(uuid4())
    info = ExternalAttempt(kind="upstream_5xx", status=503, attempts=2)

    class FailedAgent:
        def __init__(self, runtime: object) -> None:
            pass

        async def run(
            self, context: RunContext, prompt: str, emit: object, *, reference_id: object = None
        ) -> RunResult:
            return RunResult(context, RuntimeOutcome(code="provider_error", external=info))

    monkeypatch.setattr(worker, "Agent", FailedAgent)
    report = asyncio.run(
        worker.run_prompts(
            ["合成请求"],
            context,
            RuntimeIdentity("deepseek", "deepseek-flash", "test", "test"),
            tmp_path / "unused",
            (),
            SyntheticExecutor(),
            "合成系统",
        )
    )
    transmitted = json.loads(json.dumps(report, default=str))
    assert transmitted["results"][0]["outcome"]["external"]["kind"] == "upstream_5xx"


def test_event_metadata_survives_process_log_without_text(tmp_path: Path) -> None:
    context = RunContext(uuid4())
    event = RuntimeEvent(
        context,
        "tool_finished",
        text="private synthetic text",
        external=ExternalAttempt(
            kind="quota_exhausted", attempts=1, cap_scope="run", used=1, limit=1
        ),
    )
    path = tmp_path / "events.jsonl"
    save_event(path, event_metadata(event))
    restored: list[RuntimeEvent] = []
    EventReader(path, context, restored.append).drain()
    assert "private" not in path.read_text(encoding="utf-8")
    assert restored[0].external == event.external


def test_evaluation_uses_bound_full_report_and_json_roundtrips_nested_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    context = RunContext(uuid4())
    runtime = GuardedRuntime(tmp_path, "synthetic-private-dsn")
    event = RuntimeEvent(
        context,
        "tool_finished",
        tool_name="search_hotel_offers",
        text="synthetic candidate text",
        external=ExternalAttempt(kind="upstream_5xx", status=503, attempts=2),
    )
    adapter = TypeAdapter(tuple[RuntimeEvent, ...])
    report: dict[str, object] = {
        "status": "blocked",
        "identity": asdict(runtime.identity),
        "events": adapter.dump_python((event,), mode="json"),
        "http_attempts": 0,
        "currency": "CNY",
        "run_accounted_cny": "0",
        "requests": [],
    }
    runtime._observe(report, context)
    assert runtime.observed_events == (event,)
    encoded = json.dumps(adapter.dump_python(runtime.observed_events, mode="json"))
    assert adapter.validate_json(encoded) == (event,)
    runtime.observed_events = ()
    runtime._observe(report, RunContext(uuid4()))
    assert runtime.observed_events == ()

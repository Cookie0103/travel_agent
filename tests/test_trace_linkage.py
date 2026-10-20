"""同轮PG锚点与脱敏span关联；每次HTTP必须具有真实独立观测，不从文本推测。"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from backend.adapters.tracing import write_trace
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeIdentity
from backend.domain.external_data import ExternalAttempt
from backend.limits import Settings
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.guard import Guard
from tests.model_bodies import request_body, response_body


def test_fixed_trace_anchor_and_identity_context_reach_all_spans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAVEL_TRACE_HMAC_KEY", "synthetic-hmac-key")
    context = RunContext(uuid4())
    started = datetime.now(UTC)
    call = uuid4()
    events = [
        RuntimeEvent(context, "started", text="synthetic-private-prompt", occurred_at=started),
        RuntimeEvent(
            context,
            "tool_started",
            tool_name="search_hotel_offers",
            tool_call_id=call,
            occurred_at=started + timedelta(milliseconds=10),
        ),
        RuntimeEvent(
            context,
            "tool_finished",
            tool_name="search_hotel_offers",
            tool_call_id=call,
            occurred_at=started + timedelta(milliseconds=20),
        ),
        RuntimeEvent(
            context,
            "completed",
            text="synthetic-private-answer",
            occurred_at=started + timedelta(milliseconds=30),
        ),
    ]
    anchor = uuid4().hex
    target = tmp_path / "trace.jsonl"
    assert (
        write_trace(
            target, events, RuntimeIdentity("fake", "scripted", "none", "none"), trace_id=anchor
        )
        == anchor
    )
    raw = target.read_text()
    assert "synthetic-private" not in raw and "synthetic-hmac-key" not in raw
    assert str(context.session_id) not in raw and str(context.user_id) not in raw
    spans = [json.loads(line) for line in raw.splitlines()]
    assert len(spans) == 3
    for span in spans:
        assert span["context"]["trace_id"] == "0x" + anchor
        attributes = span["attributes"]
        assert len(attributes["langfuse.session.id"]) == 64
        assert len(attributes["langfuse.user.id"]) == 64
        assert attributes["langfuse.trace.metadata.run_id"] == str(context.run_id)
        assert "offline" in attributes["langfuse.trace.tags"]


def test_model_attempt_spans_use_only_observed_safe_metadata(tmp_path: Path) -> None:
    context = RunContext(uuid4())
    now = datetime.now(UTC)
    start = int(now.timestamp() * 1_000_000_000)
    events = [
        RuntimeEvent(context, "started", occurred_at=now),
        RuntimeEvent(context, "completed", occurred_at=now + timedelta(seconds=2)),
    ]
    attempts = [
        {
            "attempt": 1,
            "started_at_ns": start,
            "ended_at_ns": start + 1000,
            "status": 503,
            "input": "synthetic-private-prompt",
            "quote": "synthetic-private-quote",
        },
        {
            "attempt": 2,
            "started_at_ns": start + 2000,
            "ended_at_ns": start + 3000,
            "status": 200,
            "input_tokens": 10,
            "output_tokens": 2,
            "output": "synthetic-private-answer",
        },
    ]
    target = tmp_path / "trace.jsonl"
    write_trace(
        target,
        events,
        RuntimeIdentity("deepseek", "deepseek-flash", "test", "test"),
        http_requests=attempts,
    )
    raw = target.read_text()
    assert "synthetic-private" not in raw
    spans = [json.loads(line) for line in raw.splitlines()]
    models = [s for s in spans if s["attributes"].get("gen_ai.operation.name") == "chat"]
    assert len(models) == 2
    assert [s["attributes"]["http.response.status_code"] for s in models] == [503, 200]
    assert models[1]["attributes"]["gen_ai.usage.input_tokens"] == 10


def test_guard_records_each_actual_http_attempt_without_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    monkeypatch.setattr(time, "sleep", lambda _: None)
    responses = iter([(503, b"synthetic-private-body"), (200, response_body())])
    guard = Guard(
        Settings("synthetic-private-key", "deepseek-flash", Decimal(5), Decimal(0)),
        Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(5)),
        lambda _: next(responses),
    )
    assert guard.accept("/v1/messages", "Bearer " + guard.token, request_body())[0] == 200
    assert len(guard.http_requests) == guard.attempts == 2
    assert [r["status"] for r in guard.http_requests] == [503, 200]
    for attempt in guard.http_requests:
        start, end = attempt["started_at_ns"], attempt["ended_at_ns"]
        assert isinstance(start, int) and isinstance(end, int) and start <= end
    assert guard.http_requests[1]["input_tokens"] == guard.observations[0]["input_tokens"]
    assert "synthetic-private" not in json.dumps(guard.http_requests)


def test_model_span_input_includes_observed_cache_tokens(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    start = int(now.timestamp() * 1_000_000_000)
    target = tmp_path / "cached.jsonl"
    context = RunContext(uuid4())
    write_trace(
        target,
        [
            RuntimeEvent(context, "started", occurred_at=now),
            RuntimeEvent(context, "completed", occurred_at=now),
        ],
        RuntimeIdentity("deepseek", "test", "test", "test"),
        http_requests=[
            {
                "started_at_ns": start,
                "ended_at_ns": start + 1000,
                "status": 200,
                "input_tokens": 10,
                "cache_read_input_tokens": 40,
                "cache_creation_input_tokens": 5,
                "output_tokens": 2,
                "complete": True,
            }
        ],
    )
    model = next(
        json.loads(line)
        for line in target.read_text().splitlines()
        if json.loads(line)["attributes"].get("gen_ai.operation.name") == "chat"
    )
    assert model["attributes"]["gen_ai.usage.input_tokens"] == 55


def test_guard_preserves_cache_counts_in_each_http_observation(tmp_path: Path) -> None:
    guard = Guard(
        Settings("synthetic-key", "deepseek-flash", Decimal(5), Decimal(0)),
        Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(5)),
        lambda _: (
            200,
            response_body(
                usage={
                    "input_tokens": 100,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 40,
                    "cache_creation_input_tokens": 5,
                }
            ),
        ),
    )
    assert guard.accept("/v1/messages", "Bearer " + guard.token, request_body())[0] == 200
    assert guard.http_requests[0]["cache_read_input_tokens"] == 40
    assert guard.http_requests[0]["cache_creation_input_tokens"] == 5


def test_tool_retry_and_relaxation_are_closed_metadata(tmp_path: Path) -> None:
    context = RunContext(uuid4())
    call = uuid4()
    now = datetime.now(UTC)
    end = RuntimeEvent(
        context,
        "tool_finished",
        tool_name="search_hotel_offers",
        tool_call_id=call,
        external=ExternalAttempt(attempts=2, recovered_from="upstream_5xx"),
        relaxation_cause="budget",
        relaxation_tier=Decimal("1.5"),
        occurred_at=now + timedelta(seconds=1),
    )
    events = [
        RuntimeEvent(context, "started", occurred_at=now),
        RuntimeEvent(
            context,
            "tool_started",
            tool_name="search_hotel_offers",
            tool_call_id=call,
            occurred_at=now,
        ),
        end,
        RuntimeEvent(context, "completed", occurred_at=now + timedelta(seconds=2)),
    ]
    target = tmp_path / "trace.jsonl"
    write_trace(target, events, RuntimeIdentity("fake", "scripted", "none", "none"))
    tool = next(
        json.loads(line)
        for line in target.read_text().splitlines()
        if json.loads(line)["name"].startswith("tool.")
    )
    assert tool["attributes"]["tool.attempts"] == 2
    assert tool["attributes"]["tool.error_kind"] == "upstream_5xx"
    assert tool["attributes"]["travel.relaxation.cause"] == "budget"
    assert tool["attributes"]["travel.relaxation.tier"] == "1.5"


def test_http_200_incomplete_stream_is_an_error_generation(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    start = int(now.timestamp() * 1_000_000_000)
    context = RunContext(uuid4())
    target = tmp_path / "trace.jsonl"
    write_trace(
        target,
        [
            RuntimeEvent(context, "started", occurred_at=now),
            RuntimeEvent(context, "failed", occurred_at=now + timedelta(seconds=1)),
        ],
        RuntimeIdentity("deepseek", "deepseek-flash", "test", "test"),
        http_requests=[
            {
                "attempt": 1,
                "status": 200,
                "complete": False,
                "started_at_ns": start,
                "ended_at_ns": start + 1000,
            }
        ],
    )
    span = next(
        json.loads(line)
        for line in target.read_text().splitlines()
        if json.loads(line)["name"] == "gen_ai.chat"
    )
    assert span["status"]["status_code"] == "ERROR"
    assert span["attributes"]["travel.response_complete"] is False


@pytest.mark.parametrize("revision", [None, 7])
def test_read_only_trace_revision_is_known_or_omitted(tmp_path: Path, revision: int | None) -> None:
    context = RunContext(uuid4())
    target = tmp_path / "trace.jsonl"
    write_trace(
        target,
        [RuntimeEvent(context, "started"), RuntimeEvent(context, "completed")],
        RuntimeIdentity("fake", "fixture", "none", "none"),
        revision=revision,
    )
    for line in target.read_text().splitlines():
        attributes = json.loads(line)["attributes"]
        if revision is None:
            assert "langfuse.trace.metadata.revision" not in attributes
        else:
            assert attributes["langfuse.trace.metadata.revision"] == revision


def test_eval_metadata_is_bound_to_all_spans_and_has_closed_keys(tmp_path: Path) -> None:
    context = RunContext(uuid4())
    target = tmp_path / "trace.jsonl"
    write_trace(
        target,
        [RuntimeEvent(context, "started"), RuntimeEvent(context, "completed")],
        RuntimeIdentity("fake", "fixture", "none", "none"),
        evaluation={
            "case_id": "v2-coverage",
            "trial": 3,
            "suite": "v2-interaction",
            "quote": "private-quote",
        },
    )
    assert "private-quote" not in target.read_text()
    for line in target.read_text().splitlines():
        attributes = json.loads(line)["attributes"]
        assert attributes["langfuse.trace.metadata.eval_case_id"] == "v2-coverage"
        assert attributes["langfuse.trace.metadata.eval_trial"] == 3
        assert "v2-interaction" in attributes["langfuse.trace.tags"]

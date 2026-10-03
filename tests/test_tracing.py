"""应用事件对应实际 OTel span；默认不联网，全文和凭据不能进入导出。"""

import json
import threading
from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from uuid import uuid4

import pytest

from backend.adapters.tracing import cloud_exporter, trace_report, write_trace
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeIdentity

IDENTITY = RuntimeIdentity("fake", "scripted", "none", "none")


def test_invalid_parameter_name_cannot_leak_into_observed_trace(tmp_path: Path) -> None:
    import asyncio

    from backend.tools.execution import execute_observed
    from backend.tools.search import DEFINITIONS, SearchExecutor

    context = RunContext(uuid4())
    recorded = [RuntimeEvent(context, "started")]
    marker = "synthetic-private-marker"
    result = asyncio.run(
        execute_observed(
            SearchExecutor(),
            context,
            "search_places",
            {"city": "京都", marker: "secret"},
            recorded.append,
            definition=DEFINITIONS[0],
        )
    )
    assert result.code == "validation"
    recorded.append(RuntimeEvent(context, "failed", code=result.code))
    path = tmp_path / "trace.jsonl"
    write_trace(path, recorded, IDENTITY)
    raw = path.read_text(encoding="utf-8")
    assert marker not in raw and "secret" not in raw
    spans = [json.loads(line) for line in raw.splitlines()]
    tool = next(span for span in spans if span["name"] == "tool.search_places")
    assert tool["attributes"]["tool.argument_keys"] == ["city"]
    assert tool["attributes"]["tool.status"] == "validation"


@pytest.mark.parametrize("kind", ["partial", "awaiting_user"])
def test_recovery_status_and_evidence_metadata_are_preserved(tmp_path: Path, kind: str) -> None:
    from typing import cast

    from backend.domain.execution import EventKind

    recorded = events()
    evidence_id = str(uuid4())
    recorded[-2] = replace(recorded[-2], request_revision=3, evidence_ids=(evidence_id,))
    recorded[-1] = replace(recorded[-1], kind=cast(EventKind, kind))
    path = tmp_path / "trace.jsonl"
    write_trace(path, recorded, IDENTITY)
    spans = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert spans[-1]["attributes"]["travel.status"] == kind
    assert spans[-1]["status"]["status_code"] == "ERROR"
    tool = next(span for span in spans if span["name"] == "tool.search_places")
    assert tool["attributes"]["travel.evidence_ids"] == [evidence_id]
    assert tool["attributes"]["travel.request_revision"] == 3


def events(*, unfinished: bool = False) -> list[RuntimeEvent]:
    context, call_id = RunContext(uuid4()), uuid4()
    start = RuntimeEvent(context, "started")
    result = [
        start,
        RuntimeEvent(context, "text", text="private prompt/answer secret"),
        RuntimeEvent(
            context,
            "tool_started",
            tool_name="search_places",
            tool_call_id=call_id,
            argument_keys=("city",),
        ),
    ]
    if not unfinished:
        result.append(
            RuntimeEvent(context, "tool_finished", tool_name="search_places", tool_call_id=call_id)
        )
    result.append(RuntimeEvent(context, "completed"))
    return [
        replace(event, occurred_at=start.occurred_at + timedelta(milliseconds=i))
        for i, event in enumerate(result)
    ]


def test_trace_uses_real_event_time_and_parentage_without_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "api_key=ambient-secret")
    path = tmp_path / "trace.jsonl"
    recorded = events()
    trace_id = write_trace(path, recorded, IDENTITY)
    raw = path.read_text(encoding="utf-8")
    spans = [json.loads(line) for line in raw.splitlines()]
    assert (
        len(spans) == 3
        and "private prompt/answer secret" not in raw
        and "ambient-secret" not in raw
    )
    by_name = {span["name"]: span for span in spans}
    root, runtime, tool = [
        by_name[name] for name in ("travel.run", "agent.fixture", "tool.search_places")
    ]
    assert root["context"]["trace_id"] == "0x" + trace_id
    assert runtime["parent_id"] == root["context"]["span_id"]
    assert tool["parent_id"] == runtime["context"]["span_id"]
    assert root["start_time"].startswith(recorded[0].occurred_at.isoformat()[:19])
    assert runtime["attributes"]["travel.usage_observed"] is False


def test_unfinished_tool_or_parent_rejection_is_error(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    write_trace(path, events(unfinished=True), IDENTITY)
    spans = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert all(s["status"]["status_code"] == "ERROR" for s in spans)
    recorded = events()
    report: dict[str, object] = {
        "status": "error",
        "events": [asdict(e) for e in recorded],
        "identity": asdict(IDENTITY),
    }
    trace_report(report, tmp_path)
    spans = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert spans[-1]["status"]["status_code"] == "ERROR"
    assert spans[-1]["end_time"].startswith(recorded[-1].occurred_at.isoformat()[:23])


def test_usage_is_from_guard_and_not_sdk_dollar_estimate(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    write_trace(
        path,
        events(),
        IDENTITY,
        requests=[
            {
                "input_tokens": 7,
                "cache_read_input_tokens": 3,
                "output_tokens": 2,
                "usage_cost_upper_cny": "0.01",
            }
        ],
        http_attempts=2,
        accounted_cny=Decimal("2.11"),
    )
    spans = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    runtime = next(s for s in spans if s["name"] == "agent.fixture")
    assert runtime["attributes"]["gen_ai.usage.input_tokens"] == 10
    assert runtime["attributes"]["travel.observed_cost_upper_cny"] == "0.01"
    assert runtime["attributes"]["travel.run_accounted_cny"] == "2.11"
    assert runtime["attributes"]["travel.usage_complete"] is False
    assert runtime["attributes"]["travel.unobserved_responses"] == 1


def test_cloud_requires_explicit_complete_configuration() -> None:
    with pytest.raises(ValueError, match="未完整配置"):
        cloud_exporter({})
    with pytest.raises(ValueError, match="HTTPS"):
        cloud_exporter(
            {
                "LANGFUSE_BASE_URL": "http://external.example",
                "LANGFUSE_PUBLIC_KEY": "public",
                "LANGFUSE_SECRET_KEY": "secret",
            }
        )


def test_bad_trace_preserves_business_result(tmp_path: Path) -> None:
    report: dict[str, object] = {
        "status": "success",
        "results": ["business result"],
        "events": ["invalid event containing private text"],
        "identity": asdict(IDENTITY),
    }
    trace_report(report, tmp_path)
    assert report["status"] == "success" and report["results"] == ["business result"]
    assert report["trace_status"] == "failed" and report["trace_error"] == "unavailable"


def test_missing_tool_start_marks_observation_gap(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    write_trace(path, [e for e in events() if e.kind != "tool_started"], IDENTITY)
    spans = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert all(s["status"]["status_code"] == "ERROR" for s in spans)


def test_old_report_without_timestamps_does_not_invent_time(tmp_path: Path) -> None:
    raw = [asdict(e) for e in events()]
    raw[0].pop("occurred_at")
    report: dict[str, object] = {"status": "success", "events": raw, "identity": asdict(IDENTITY)}
    trace_report(report, tmp_path)
    assert report["trace_status"] == "failed"
    assert not (tmp_path / "trace.jsonl").exists()


def test_disk_failure_does_not_claim_trace_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("private disk path")

    monkeypatch.setattr("backend.adapters.tracing.ConsoleSpanExporter.export", fail)
    report: dict[str, object] = {
        "status": "success",
        "events": [asdict(e) for e in events()],
        "identity": asdict(IDENTITY),
    }
    trace_report(report, tmp_path)
    assert report["status"] == "success" and report["trace_status"] == "failed"
    assert "private disk path" not in json.dumps(report, default=str)


def test_official_otlp_exporter_sends_private_summary_to_local_collector(tmp_path: Path) -> None:
    received: list[tuple[str, str | None, str | None, bytes]] = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.append(
                (
                    self.path,
                    self.headers.get("Authorization"),
                    self.headers.get("x-langfuse-ingestion-version"),
                    self.rfile.read(int(self.headers["Content-Length"])),
                )
            )
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        exporter = cloud_exporter(
            {
                "LANGFUSE_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                "LANGFUSE_PUBLIC_KEY": "local-public",
                "LANGFUSE_SECRET_KEY": "local-secret",
            }
        )
        write_trace(tmp_path / "trace.jsonl", events(), IDENTITY, exporter=exporter)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert len(received) == 1
    assert all(path == "/api/public/otel/v1/traces" for path, _, _, _ in received)
    assert all(
        auth and auth.startswith("Basic ") and version == "4" for _, auth, version, _ in received
    )
    assert all(
        b"private prompt/answer secret" not in body and b"local-secret" not in body
        for _, _, _, body in received
    )

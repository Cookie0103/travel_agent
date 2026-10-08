"""Structured stage metadata is bounded; read tools/text cannot invent a commit."""

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from backend.adapters.tracing import write_trace
from backend.domain.execution import (
    BusinessResult,
    RunContext,
    RuntimeEvent,
    RuntimeIdentity,
    event_metadata,
)
from backend.tools.contracts import ToolResult
from backend.tools.execution import execute_observed, stage_result
from backend.tools.travel import DEFINITIONS


def test_stage_metadata_requires_valid_server_ids_report_and_safe_reason() -> None:
    assert (
        stage_result(
            ToolResult(
                {"draft_id": "fake", "plan_id": "fake", "validation": {"status": "complete"}}
            )
        )
        is None
    )
    assert (
        stage_result(
            ToolResult(
                {
                    "draft_id": str(uuid4()),
                    "plan_id": str(uuid4()),
                    "validation": {"status": "model_says_ok"},
                }
            )
        )
        is None
    )
    result = stage_result(ToolResult({}, code="blocked", detail=("synthetic-private-input",)))
    assert result is not None and result.kind == "stage_failed" and result.reason == "other"
    assert "synthetic-private-input" not in json.dumps(asdict(result))


def test_read_only_result_cannot_mark_confirmation_and_metadata_is_not_public_trace(
    tmp_path: Path,
) -> None:
    context = RunContext(uuid4())
    result = ToolResult(
        {"draft_id": str(uuid4()), "plan_id": str(uuid4()), "validation": {"status": "partial"}}
    )

    class Executor:
        async def execute(self, *args: object) -> ToolResult:
            return result

    events = [RuntimeEvent(context, "started")]
    for name in ("get_saved_plan", "stage_plan_change"):
        definition = next(d for d in DEFINITIONS if d.name == name)
        asyncio.run(
            execute_observed(Executor(), context, name, {}, events.append, definition=definition)
        )
    assert events[2].business_result is None
    staged = events[-1].business_result
    assert staged is not None and staged.kind == "draft_staged"
    assert event_metadata(events[-1]).business_result == staged
    path = tmp_path / "trace.jsonl"
    write_trace(
        path,
        [*events, RuntimeEvent(context, "completed")],
        RuntimeIdentity("fake", "fixture", "none", "none"),
    )
    output = path.read_text()
    assert str(staged.draft_id) not in output and str(staged.plan_id) not in output
    assert "business_result" not in output


def test_business_result_cannot_claim_confirmation_without_a_positive_integer_version() -> None:
    import pytest
    from pydantic import TypeAdapter, ValidationError

    for value in (0, True, "1"):
        with pytest.raises(ValidationError):
            TypeAdapter(BusinessResult).validate_python(
                {"kind": "confirmed", "plan_id": str(uuid4()), "version": value}
            )

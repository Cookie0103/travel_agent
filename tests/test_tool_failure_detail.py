"""工具失败的TRACE诊断标签：说明原因类别，但不泄露输入值、模型自造字段名或消息正文。"""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest

from backend import trace_log
from backend.domain.execution import RunContext
from backend.domain.itinerary import ValidationCheck, ValidationReport
from backend.services.common import ServiceError
from backend.services.travel import TravelService
from backend.tools.contracts import ToolResult
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor, report_detail

SECRET = "zz-private-trip-text"


def executor(max_validations: int = 4) -> TravelToolExecutor:
    fake = cast(TravelService, type("T", (), {"live": None, "database": None})())
    return TravelToolExecutor(fake, max_validations=max_validations)


def run(context: RunContext, name: str, arguments: dict[str, object]) -> ToolResult:
    return asyncio.run(executor().execute(context, name, arguments))


def test_pydantic_failure_lists_paths_only_without_values_or_extra_names() -> None:
    context = RunContext(uuid4())
    bad: dict[str, object] = {
        "expected_revision": SECRET,
        "items": [{"place_evidence_id": SECRET, "start": SECRET, "note": SECRET * 10}],
        f"field-{SECRET}": SECRET,
    }
    result = run(context, "validate_itinerary", bad)
    assert result.code == "validation" and result.detail[0] == "schema"
    text = json.dumps(result.detail)
    assert SECRET not in text
    assert "expected_revision:int_type" in result.detail
    assert len(result.detail) <= 1 + 6 + 2
    assert result.detail[-2:] == ("repair_round:0", "max_validations:4")


def test_model_invented_field_names_are_not_logged() -> None:
    bad: dict[str, object] = {"expected_revision": 0, "items": [], f"f-{SECRET}": 1}
    detail = run(RunContext(uuid4()), "validate_itinerary", bad).detail
    assert "<extra>:extra_forbidden" in detail and SECRET not in json.dumps(detail)


def test_unknown_tool_and_call_cap_have_distinct_details() -> None:
    context = RunContext(uuid4())
    assert run(context, "nope", {}).detail == ("unregistered_tool",)
    capped = TravelToolExecutor(
        cast(TravelService, type("T", (), {"live": None, "database": None})()), max_calls=0
    )
    name = DEFINITIONS[0].name
    assert asyncio.run(capped.execute(context, name, {})).detail == ("tool_call_cap",)


def test_repair_limit_is_reported_as_its_own_reason() -> None:
    one = executor(max_validations=1)
    one.validations = 1
    with pytest.raises(ServiceError) as caught:
        one._take_validation(cast(Any, object()))
    assert caught.value.reason == "repair_limit" and caught.value.code == "blocked"


def test_report_detail_has_counts_and_check_codes_not_names() -> None:
    checks = (
        ValidationCheck(subject=SECRET, status="verified", code="budget", message=SECRET),
        ValidationCheck(subject=SECRET, status="unknown", code="route_duration", message=SECRET),
        ValidationCheck(subject=SECRET, status="conflict", code="opening_hours", message=SECRET),
    )
    report = ValidationReport(
        status="conflict", checks=checks, known_cost=Decimal(0), estimated_cost=Decimal(0)
    )
    detail = report_detail(report)
    assert detail == (
        "report:conflict",
        "counts:v1/u1/c1",
        "opening_hours:conflict",
        "route_duration:unknown",
    )
    assert SECRET not in json.dumps(detail)


def test_tool_end_trace_carries_detail_and_omits_it_when_absent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(trace_log, "_stdout", True)

    class Fake:
        def __init__(self, result: ToolResult) -> None:
            self.result = result

        async def execute(self, *args: object) -> ToolResult:
            return self.result

    context = RunContext(uuid4())
    failed = ToolResult({}, code="conflict", detail=("service:409", "revision_stale"))
    fine = ToolResult({"a": 1})
    for result in (failed, fine):
        asyncio.run(execute_observed(Fake(result), context, "nope", {}, lambda event: None))
    ends = [
        json.loads(line.removeprefix("TRACE "))
        for line in capsys.readouterr().out.splitlines()
        if '"tool_end"' in line
    ]
    assert ends[0]["detail"] == ["service:409", "revision_stale"] and ends[0]["code"] == "conflict"
    assert ends[1]["detail"] is None
    assert "now" not in ends[0] and datetime.now(UTC).year >= 2026

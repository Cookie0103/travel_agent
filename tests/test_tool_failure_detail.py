"""工具失败的TRACE诊断标签：说明原因类别，但不泄露输入值、模型自造字段名或消息正文。"""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest

from backend import trace_log
from backend.domain.execution import RunContext, RuntimeEvent, tool_reason
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


def test_oversized_hotel_search_is_compacted_then_trimmed_whole_cards() -> None:
    from backend.tools.contracts import RESULT_LIMIT
    from backend.tools.travel import bounded_offers

    offers: list[dict[str, object]] = [
        {
            "offer_id": str(uuid4()),
            "evidence_id": str(uuid4()),
            "hotel_name": "酒店" * 10,
            "total": str(20000 - index * 100),
            "booking_url": "https://example.test/" + "a" * 1500,
            "stay": {"city": "京都"},
            "image_url": "https://example.test/i.jpg",
            "request_revision": 1,
        }
        for index in range(6)
    ]
    kept, trimmed = bounded_offers(offers, ("w",))
    assert trimmed and 1 <= len(kept) < 6
    totals = [str(o["total"]) for o in kept]
    assert totals == [str(o["total"]) for o in offers[: len(kept)]]  # D7：上游顺序
    assert all("stay" not in o and "image_url" not in o for o in kept)
    payload = ToolResult({"offers": kept}, warnings=("w", "x" * 60)).payload()
    assert len(json.dumps(payload, ensure_ascii=False)) <= RESULT_LIMIT
    small, untouched = bounded_offers(offers[:2], ("w",))
    assert len(small) == 2 and not untouched


def test_offer_compaction_preserves_upstream_order_instead_of_sorting_price() -> None:
    from backend.tools.travel import bounded_offers

    offers: list[dict[str, object]] = [
        {"offer_id": str(uuid4()), "evidence_id": str(uuid4()), "total": str(price)}
        for price in [30000, 10000, 20000]
    ]
    kept, trimmed = bounded_offers(offers, ())
    assert not trimmed and [row["offer_id"] for row in kept] == [row["offer_id"] for row in offers]


def test_tool_reason_maps_known_details_and_never_passes_free_text() -> None:
    assert tool_reason(None, ("tool_call_cap",)) is None
    assert tool_reason("blocked", ("tool_call_cap",)) == "tool_call_cap"
    assert tool_reason("blocked", ("service:429", "repair_limit")) == "repair_limit"
    assert tool_reason("blocked", ("service:404", "untagged")) == "not_found"
    assert tool_reason("blocked", ("service:404", "evidence_missing")) == "evidence_missing"
    assert tool_reason("unavailable", ("local_error", "OSError")) == "other"
    assert tool_reason("blocked", (SECRET, "other")) == "other"
    assert tool_reason("blocked", ()) == "other"


def test_unregistered_tool_event_carries_reason() -> None:
    events: list[RuntimeEvent] = []
    asyncio.run(execute_observed(executor(), RunContext(uuid4()), "nope", {}, events.append))
    finished = next(e for e in events if e.kind == "tool_finished")
    assert (finished.code, finished.reason) == ("blocked", "unregistered_tool")


def test_identical_blocked_call_is_not_retried_or_counted() -> None:
    context = RunContext(uuid4())
    guarded = executor(max_validations=1)
    guarded.validations = 1  # 修复轮次已用完：同一提案再提交必然repair_limit
    item = {
        "place_evidence_id": str(uuid4()),
        "start": "2026-11-03T10:00+09:00",
        "end": "2026-11-03T11:00+09:00",
    }
    args: dict[str, object] = {"expected_revision": 1, "items": [item]}
    first = asyncio.run(guarded.execute(context, "validate_itinerary", args))
    calls = guarded.calls
    second = asyncio.run(guarded.execute(context, "validate_itinerary", {**args}))
    assert "repair_limit" in first.detail and second.detail[0] == "repeat_blocked"
    assert second.code == "blocked" and guarded.calls == calls
    assert tool_reason(second.code, second.detail) == "repeat_blocked"
    other = asyncio.run(
        guarded.execute(context, "validate_itinerary", {**args, "expected_revision": 2})
    )
    assert "repair_limit" in other.detail  # 参数不同则照常执行，不受记忆影响
    # 成功调用后相同请求重新执行见 integration/test_blocked_reasons.py。


def test_call_cap_is_never_remembered_as_repeat() -> None:
    capped = TravelToolExecutor(
        cast(TravelService, type("T", (), {"live": None, "database": None})()), max_calls=0
    )
    name = DEFINITIONS[0].name
    context = RunContext(uuid4())
    for _ in range(2):
        assert asyncio.run(capped.execute(context, name, {})).detail == ("tool_call_cap",)
    assert not capped.rejected


def test_repeated_stage_after_repair_cap_keeps_original_stage_reason() -> None:
    context = RunContext(uuid4())
    guarded = executor(max_validations=1)
    guarded.validations = 1
    item = {
        "place_evidence_id": str(uuid4()),
        "start": "2026-11-03T10:00+09:00",
        "end": "2026-11-03T11:00+09:00",
    }
    args: dict[str, object] = {
        "change": {"kind": "initial", "proposal": {"expected_revision": 1, "items": [item]}}
    }

    class FakePlans:
        async def stage(self, context: RunContext, parsed: Any, *, before_validate: Any) -> Any:
            before_validate(parsed.change.proposal)

    guarded.plans = cast(Any, FakePlans())
    events: list[RuntimeEvent] = []
    definition = next(d for d in DEFINITIONS if d.name == "stage_plan_change")
    for _ in range(2):
        asyncio.run(
            execute_observed(
                guarded, context, "stage_plan_change", args, events.append, definition=definition
            )
        )
    finished = [e for e in events if e.kind == "tool_finished"]
    assert [e.reason for e in finished] == ["repair_limit", "repeat_blocked"]
    assert guarded.calls == 1
    result = finished[1].business_result
    assert result is not None and result.kind == "stage_failed" and result.reason == "repair_limit"

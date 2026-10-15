"""M3.4：固定顺序只约束调用，不跳过原工具校验，也不把失败当完成阶段。"""

from dataclasses import replace
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext
from backend.tools.contracts import ToolResult
from backend.tools.workflow import OrderedTools, workflow_guidance
from eval.run import token_totals


class RecordingTools:
    def __init__(self, result: ToolResult | None = None) -> None:
        self.result = result if result is not None else ToolResult({"actual": True})
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        self.calls.append((name, arguments))
        return self.result


@pytest.mark.asyncio
async def test_fixed_workflow_keeps_parameters_and_requires_actual_prior_stage() -> None:
    original = RecordingTools()
    fixed = OrderedTools(original, "hotel")
    context = RunContext(uuid4())
    assert (await fixed.execute(context, "present_travel_result", {})).code == "blocked"
    assert not original.calls
    assert (await fixed.execute(context, "update_travel_request", {"actual": 1})).code is None
    arguments: dict[str, object] = {"expected_revision": 7, "limit": 3}
    assert await fixed.execute(context, "search_hotel_offers", arguments) is original.result
    assert original.calls[-1] == ("search_hotel_offers", arguments)
    assert (await fixed.execute(context, "load_skill", {"name": "hotel-comparison"})).code is None
    assert (await fixed.execute(context, "present_travel_result", {})).code is None
    assert (await fixed.execute(context, "search_hotel_offers", {})).code == "blocked"
    assert (await fixed.execute(context, "update_travel_request", {})).code == "blocked"
    assert (await fixed.execute(context, "book_hotel", {})).code == "blocked"
    assert (
        await fixed.execute(replace(context, run_id=uuid4()), "load_skill", {})
    ).code == "blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [ToolResult({}, code="validation"), ToolResult({}, empty=True)])
async def test_failed_or_empty_stage_cannot_advance_but_can_retry(result: ToolResult) -> None:
    original = RecordingTools(result)
    fixed = OrderedTools(original, "hotel")
    context = RunContext(uuid4())
    assert await fixed.execute(context, "search_hotel_offers", {}) is result
    assert (await fixed.execute(context, "present_travel_result", {})).code == "blocked"
    original.result = ToolResult({"offers": ["server-owned"]})
    assert (await fixed.execute(context, "search_hotel_offers", {})).code is None
    assert (await fixed.execute(context, "present_travel_result", {})).code is None


def test_fixed_instructions_do_not_contain_grader_expectations() -> None:
    text = workflow_guidance("itinerary")
    assert "validate_itinerary" in text and "确认" in text and "缺少条件先追问" in text
    assert text.index("get_place_facts") < text.index("search_hotel_offers")
    assert text.index("search_hotel_offers") < text.index("estimate_routes")
    assert "required_tools" not in text and "case_id" not in text


@pytest.mark.asyncio
async def test_full_fixed_trip_includes_hotels_before_routes_and_validation() -> None:
    original = RecordingTools()
    fixed = OrderedTools(original, "itinerary")
    context = RunContext(uuid4())
    for name in (
        "update_travel_request",
        "get_place_facts",
        "get_place_facts",
        "search_hotel_offers",
        "estimate_routes",
        "validate_itinerary",
        "validate_itinerary",
        "stage_plan_change",
        "present_travel_result",
    ):
        assert (await fixed.execute(context, name, {})).code is None
    assert len(original.calls) == 9


def test_token_report_is_unknown_for_missing_or_partial_usage() -> None:
    row = {
        "input_tokens": 10,
        "cache_read_input_tokens": 2,
        "cache_creation_input_tokens": 0,
        "output_tokens": 3,
    }
    assert token_totals({"requests": [row, row], "http_attempts": 2}) == {
        "input_tokens": 20,
        "cache_read_input_tokens": 4,
        "cache_creation_input_tokens": 0,
        "output_tokens": 6,
    }
    assert token_totals({"requests": [row], "http_attempts": 2}) is None
    assert token_totals({"requests": [{**row, "input_tokens": True}], "http_attempts": 1}) is None
    assert token_totals({}) is None

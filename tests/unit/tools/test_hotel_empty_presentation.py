"""空/错误是展示事实，不能改成工具成功或携带私有输入。"""

import asyncio
from uuid import uuid4

import pytest

from backend.domain.execution import ErrorCode, RunContext, RuntimeEvent
from backend.services.views import HotelPresentation
from backend.tools.contracts import ToolResult
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS


class Executor:
    def __init__(self, result: ToolResult, *, raises: bool = False) -> None:
        self.result, self.raises, self.calls = result, raises, 0

    async def execute(self, *args: object) -> ToolResult:
        self.calls += 1
        if self.raises:
            raise OSError("synthetic-private-error")
        return self.result


def observe(
    name: str, result: ToolResult, *, raises: bool = False
) -> tuple[ToolResult, list[RuntimeEvent]]:
    context = RunContext(uuid4(), uuid4())
    arguments: dict[str, object] = {
        "component": "hotel_comparison",
        "private": "synthetic-private-input",
    }
    events: list[RuntimeEvent] = []
    executor = Executor(result, raises=raises)
    returned = asyncio.run(
        execute_observed(
            executor,
            context,
            name,
            arguments,
            events.append,
            definition=next(d for d in DEFINITIONS if d.name == name),
        )
    )
    assert executor.calls == 1
    return returned, events


@pytest.mark.parametrize("name", ["search_hotel_offers", "refresh_hotel_offer"])
@pytest.mark.parametrize(
    "code",
    [
        None,
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
def test_empty_or_failed_hotel_read_emits_owned_empty_panel_without_changing_result(
    name: str,
    code: ErrorCode | None,
) -> None:
    result = ToolResult(
        {"offers": []} if code is None else {},
        code=code,
        empty=code is None,
        suggestion="synthetic-private-suggestion",
        detail=("synthetic-private-detail",),
    )
    returned, events = observe(name, result)
    assert returned is result
    assert [e.kind for e in events] == ["tool_started", "tool_finished", "presentation"]
    finished, shown = events[-2:]
    assert shown.context == finished.context and shown.tool_call_id == finished.tool_call_id
    assert finished.code == code and finished.business_result is None
    assert shown.presentation is not None
    payload = shown.presentation
    panel = HotelPresentation.model_validate(payload["data"])
    assert not panel.cards and not panel.comparison.comparable
    assert panel.comparison.lowest_offer_ids == () and panel.comparison.reasons
    assert payload["status"] == ("error" if code else "empty")
    error = payload["error"]
    if code is None:
        assert error is None
    else:
        assert isinstance(error, dict) and error["code"] == code
    assert "synthetic-private" not in str(payload)


def test_present_hotel_failure_and_unexpected_read_error_emit_panel() -> None:
    result = ToolResult({}, code="conflict", detail=("lodging_budget_conflict",))
    _, events = observe("present_travel_result", result)
    assert events[-1].kind == "presentation"
    assert "以哪个为准" in str(events[-1].presentation)
    returned, events = observe("search_hotel_offers", result, raises=True)
    assert returned.code == "unavailable" and events[-1].kind == "presentation"
    assert "synthetic-private" not in str(events[-1].presentation)


def test_successful_read_and_unrelated_failures_do_not_invent_hotel_presentation() -> None:
    events: list[RuntimeEvent]
    for name, result in (
        ("search_hotel_offers", ToolResult({"offers": [{"offer_id": "synthetic"}]})),
        ("search_places", ToolResult({}, code="unavailable")),
    ):
        _, events = observe(name, result)
        assert [e.kind for e in events] == ["tool_started", "tool_finished"]
    events = []
    asyncio.run(
        execute_observed(
            Executor(ToolResult({}, code="blocked")),
            RunContext(uuid4()),
            "present_travel_result",
            {"component": "itinerary"},
            events.append,
            definition=next(d for d in DEFINITIONS if d.name == "present_travel_result"),
        )
    )
    assert events[-1].kind == "tool_finished"

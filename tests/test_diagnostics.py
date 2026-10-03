"""诊断只使用绑定的私有事实；错误码/不完整关联/冲突证据不能强猜根因。"""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.travel_request import TravelConditions
from eval.diagnostics import ArgumentFact, ConditionFact, diagnose


def evidence() -> tuple[tuple[RuntimeEvent, ...], ArgumentFact]:
    context, call_id = RunContext(uuid4()), uuid4()
    now = datetime.now(UTC)
    events = (
        RuntimeEvent(context, "started", occurred_at=now),
        RuntimeEvent(
            context,
            "tool_started",
            tool_name="search_places",
            tool_call_id=call_id,
            occurred_at=now,
        ),
        RuntimeEvent(
            context,
            "tool_finished",
            tool_name="search_places",
            tool_call_id=call_id,
            code="validation",
            occurred_at=now + timedelta(seconds=1),
        ),
        RuntimeEvent(context, "completed", occurred_at=now + timedelta(seconds=2)),
    )
    return events, ArgumentFact(context, call_id, {"private-input": "private-value"})


def test_completed_does_not_replace_business_grading_and_recovery_is_not_failure() -> None:
    events, fact = evidence()
    failed = diagnose(events, (fact,), business_passed=False, trace_id="private-path")
    assert failed.cause == "tool_selection_or_args" and failed.event_index == 1
    assert failed.trace_id is None and "private" not in json.dumps(asdict(failed))
    assert diagnose(events, (fact,), business_passed=True).cause is None
    assert diagnose(events, (), business_passed=False).cause == "unknown"


@pytest.mark.parametrize(
    "damage", ["run", "call", "duplicate", "order", "context", "no_end", "valid_arguments"]
)
def test_wrong_or_disproved_attachment_is_unknown(damage: str) -> None:
    events, fact = evidence()
    if damage == "run":
        fact = replace(fact, context=replace(fact.context, run_id=uuid4()))
    elif damage == "call":
        fact = replace(fact, tool_call_id=uuid4())
    elif damage == "duplicate":
        events = (*events[:3], events[2], events[3])
    elif damage == "order":
        events = (events[0], events[2], events[1], events[3])
    elif damage == "context":
        events = (replace(events[0], context=RunContext(uuid4())), *events[1:])
    elif damage == "no_end":
        events = (*events[:2], events[3])
    else:
        fact = replace(fact, arguments={"city": "京都"})
    assert diagnose(events, (fact,), business_passed=False).cause == "unknown"


def test_distinct_roots_are_not_arbitrarily_selected() -> None:
    events, invalid = evidence()
    call = uuid4()
    wrong = (
        RuntimeEvent(
            invalid.context,
            "tool_started",
            tool_name="update_travel_request",
            tool_call_id=call,
            occurred_at=events[-1].occurred_at,
        ),
        RuntimeEvent(
            invalid.context,
            "tool_finished",
            tool_name="update_travel_request",
            tool_call_id=call,
            request_revision=2,
            occurred_at=events[-1].occurred_at,
        ),
    )
    fact = ConditionFact(
        invalid.context, call, TravelConditions(adults=2), TravelConditions(adults=3), 2
    )
    assert diagnose((*events, *wrong), (invalid, fact), business_passed=False).cause == "unknown"

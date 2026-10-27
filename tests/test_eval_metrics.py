"""plan05：逐调用分母/合法但语义错误的参数/未知事实，首进度不计启动或终态。"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeEvent
from eval.cases import Case
from eval.diagnostics import ArgumentFact
from eval.metrics import first_progress_seconds, tool_call_accuracy
from eval.report import measured_summary


def setup() -> tuple[Case, RunContext, tuple[RuntimeEvent, ...]]:
    context, call_id = RunContext(uuid4()), uuid4()
    case = Case(
        case_id="metric-control",
        source="self-authored",
        adaptation="call facts",
        input="查询京都景点",
        allowed_tools=["search_places"],
    )
    return (
        case,
        context,
        (
            RuntimeEvent(context, "tool_started", tool_name="search_places", tool_call_id=call_id),
            RuntimeEvent(
                context,
                "tool_finished",
                tool_name="search_places",
                tool_call_id=call_id,
                result_empty=False,
            ),
        ),
    )


def test_successful_tool_without_parameter_evidence_stays_unknown() -> None:
    case, _, events = setup()
    result = tool_call_accuracy(case, events)
    assert result["total"] == result["unknown"] == 1
    assert result["accuracy"] is None and result["correct"] == 0


def test_exact_independent_parameter_expectation_normalizes_defaults() -> None:
    case, context, events = setup()
    call_id = events[0].tool_call_id
    assert call_id is not None
    actual = ArgumentFact(context, call_id, {"city": "京都", "query": "寺庙", "limit": 5})
    expected = ArgumentFact(context, call_id, {"city": "京都", "query": "寺庙"})
    good = tool_call_accuracy(case, events, (actual,), (expected,))
    assert good["correct"] == 1 and good["accuracy"] == 1
    wrong = replace(actual, arguments={"city": "京都", "query": "博物馆", "limit": 5})
    bad = tool_call_accuracy(case, events, (wrong,), (expected,))
    assert bad["incorrect"] == 1 and bad["accuracy"] == 0
    assert "博物馆" not in str(bad)  # 参数原文只留私有事实。


def test_schema_valid_but_wrong_dates_are_incorrect_against_independent_ground_truth() -> None:
    case, context, events = setup()
    case = case.model_copy(update={"allowed_tools": ["update_travel_request"]})
    events = tuple(replace(e, tool_name="update_travel_request") for e in events)
    call_id = events[0].tool_call_id
    assert call_id is not None
    expected = ArgumentFact(
        context,
        call_id,
        {"expected_revision": 1, "set": {"start_date": "2026-11-03", "end_date": "2026-11-05"}},
    )
    actual = replace(
        expected,
        arguments={
            "expected_revision": 1,
            "set": {"start_date": "2026-11-10", "end_date": "2026-11-12"},
        },
    )
    result = tool_call_accuracy(case, events, (actual,), (expected,))
    assert result["incorrect"] == 1 and result["accuracy"] == 0


@pytest.mark.parametrize(
    "fault",
    [
        "foreign_run",
        "duplicate_fact",
        "invalid_expectation",
        "unpaired",
        "duplicated_start",
        "duplicated_end",
        "foreign_end",
        "reverse_time",
    ],
)
def test_bad_fact_attachment_or_trace_never_proves_accuracy(fault: str) -> None:
    case, context, events = setup()
    call_id = events[0].tool_call_id
    assert call_id is not None
    fact = ArgumentFact(context, call_id, {"city": "京都", "query": "寺庙"})
    actual: tuple[ArgumentFact, ...] = (fact,)
    expected: tuple[ArgumentFact, ...] = (fact,)
    if fault == "foreign_run":
        actual = (replace(fact, context=replace(context, run_id=uuid4())),)
    elif fault == "duplicate_fact":
        actual = (fact, fact)
    elif fault == "invalid_expectation":
        expected = (replace(fact, arguments={"user_id": "private"}),)
    elif fault == "unpaired":
        events = events[:1]
    elif fault == "duplicated_start":
        events = (events[0], *events)
    elif fault == "duplicated_end":
        events = (*events, events[-1])
    elif fault == "foreign_end":
        events = (events[0], replace(events[1], context=replace(context, run_id=uuid4())))
    else:
        events = (
            events[0],
            replace(events[1], occurred_at=events[0].occurred_at - timedelta(seconds=1)),
        )
    result = tool_call_accuracy(case, events, actual, expected)
    assert result["accuracy"] is None and result["correct"] == 0


def test_invalid_parameters_and_forbidden_selection_count_all_attempts() -> None:
    case, context, events = setup()
    call_id = events[0].tool_call_id
    assert call_id is not None
    fact = ArgumentFact(context, call_id, {"city": "京都", "limit": True})
    invalid = tool_call_accuracy(case, events, (fact,))
    assert invalid["incorrect"] == invalid["total"] == 1
    forbidden = case.model_copy(update={"allowed_tools": []})
    assert tool_call_accuracy(forbidden, events)["incorrect"] == 1
    dependency = (events[0], replace(events[1], code="unavailable"))
    assert tool_call_accuracy(case, dependency)["unknown"] == 1
    # 同一错误码也可能来自业务状态；没有原参数不能假定schema或语义错误。
    validation = (events[0], replace(events[1], code="validation"))
    assert tool_call_accuracy(case, validation)["unknown"] == 1


def test_first_progress_excludes_started_completed_and_empty_text_and_wrong_run() -> None:
    context = RunContext(uuid4())
    start = datetime(2026, 10, 3, tzinfo=UTC)
    end = start + timedelta(seconds=10)
    events = (
        RuntimeEvent(context, "started", occurred_at=start),
        RuntimeEvent(context, "text", text="  ", occurred_at=start),
        RuntimeEvent(context, "text", text="收到，我先查一下。", occurred_at=start),
        RuntimeEvent(replace(context, run_id=uuid4()), "text", text="wrong", occurred_at=start),
        RuntimeEvent(
            context,
            "tool_started",
            tool_name="search_places",
            occurred_at=start + timedelta(seconds=2),
        ),
        RuntimeEvent(context, "completed", occurred_at=end),
    )
    assert first_progress_seconds(start, end, context, events) == 2
    assert first_progress_seconds(start, end, context, events[:4]) is None
    for timestamp in (
        start - timedelta(seconds=1),
        end + timedelta(seconds=1),
        start.replace(tzinfo=None),
    ):
        assert (
            first_progress_seconds(
                start, end, context, (replace(events[4], occurred_at=timestamp),)
            )
            is None
        )


def test_summary_progress_and_tool_denominators_keep_unknown_and_old_rows() -> None:
    rows: list[dict[str, object]] = [
        {
            "repeat": 1,
            "status": "passed",
            "elapsed_seconds": 8,
            "first_progress_seconds": 2,
            "tool_call_accuracy": {
                "total": 1,
                "correct": 1,
                "incorrect": 0,
                "unknown": 0,
                "events_consistent": True,
            },
        },
        {"repeat": 1, "status": "error", "first_progress_seconds": None},
        {"repeat": 1, "status": "not_run"},
    ]
    summary = measured_summary(rows, 1)
    assert summary["first_progress_unknown_n"] == 1
    assert summary["first_progress_seconds"] == {
        "measured_n": 1,
        "p50": 2,
        "p95": 2,
        "method": "nearest-rank",
    }
    assert summary["tool_call_accuracy"] == {
        "total": None,
        "correct": None,
        "incorrect": None,
        "unknown": None,
        "measured_subtotal": {"total": 1, "correct": 1, "incorrect": 0, "unknown": 0},
        "unknown_cases": 1,
        "accuracy": None,
        "scope": "all started calls; unknown semantic parameters remain unscored",
    }

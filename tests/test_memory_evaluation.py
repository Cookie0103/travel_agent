"""记忆质量按明确期望计TP/FP/FN，不把来源阻断或空预测伪装成满分。"""

from pathlib import Path

from eval.memory_metrics import memory_scores
from eval.suites import load_suite


def test_memory_suite_has_twenty_cases_and_all_seven_categories() -> None:
    cases, _ = load_suite(Path(__file__).resolve().parents[1], "v2-memory", "dev")
    assert len(cases) == 20
    assert {case.memory_category for case in cases} == {
        "extraction",
        "trip",
        "negation",
        "third_party",
        "update",
        "abstain",
        "poison",
    }


def test_memory_scoring_wrong_scope_is_not_correct_and_empty_is_unmeasured() -> None:
    expected = [{"op": "ADD", "key": "pace", "values": ["特种兵"], "scope": "trip"}]
    prediction = [{"op": "ADD", "key": "pace", "value": "特种兵", "scope": "long_term"}]
    score = memory_scores(expected, prediction, invalid_attempts=0)
    assert (
        score["true_positive"] == 0
        and score["false_positive"] == 1
        and score["false_negative"] == 1
    )
    assert score["precision"] == score["recall"] == 0
    empty = memory_scores([], [], invalid_attempts=1)
    assert empty["precision"] is None and empty["recall"] is None
    assert empty["exact"] is False


def test_memory_failures_distinguish_invalid_proposals_from_infrastructure() -> None:
    from uuid import uuid4

    from backend.domain.execution import RunContext, RuntimeEvent
    from eval.memory_metrics import proposal_failures

    context = RunContext(uuid4(), uuid4(), uuid4())
    events = tuple(
        RuntimeEvent(context=context, kind="tool_finished", tool_name="propose_memory", code=code)
        for code in ("validation", "blocked", "conflict", "timeout", "unavailable")
    )
    assert proposal_failures(events) == {"invalid_attempts": 3, "unavailable_attempts": 2}

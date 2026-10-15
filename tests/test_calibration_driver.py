"""标注池先保证不同任务，再取后续trial；比较不能接受未知标签。"""

import pytest

from eval.calibration import ComparisonScore, comparison_pairs, task_context, varied_rows


def test_annotation_selection_prefers_unique_tasks_before_repeat_trials() -> None:
    rows: list[dict[str, object]] = [
        {"case_id": name, "status": "passed", "text": name}
        for name in ("one", "one", "one", "two", "three")
    ]
    assert [row["case_id"] for row in varied_rows(rows)] == ["one", "two", "three", "one", "one"]
    with pytest.raises(ValueError):
        ComparisonScore.model_validate({"preferred": "not_observed", "reason": "未知"})


def test_last_answer_calibration_contains_actual_click_without_hidden_goal() -> None:
    task = task_context(
        {
            "user_input": "比较酒店",
            "goal": "private hidden target",
            "dialogue": [{"user": {"kind": "choice", "text": "保持预算", "option_id": "keep"}}],
        }
    )
    assert "比较酒店" in task and "保持预算" in task and "keep" in task
    assert "hidden" not in task


def test_position_comparison_requires_same_actual_task_and_conditions() -> None:
    positive: dict[str, object] = {
        "case_id": "scenario",
        "status": "passed",
        "text": "回答A",
        "user_input": "接受预算",
        "conditions": {"budget": "20000"},
    }
    negative = {**positive, "status": "failed", "text": "回答B"}
    assert not comparison_pairs([positive, {**negative, "user_input": "保持预算"}])
    assert not comparison_pairs([positive, {**negative, "conditions": {"budget": "10000"}}])
    assert comparison_pairs([positive, negative]) == [(positive, negative)]
    assert not comparison_pairs(
        [{**positive, "user_input": "x" * 12000}, {**negative, "user_input": "x" * 12000}]
    )

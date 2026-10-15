"""云评测只发送可观察的有限数值，未知和评审正文不得成为分数。"""

import pytest

from eval.publish_v2 import match_triage, triage_scores, trial_scores


def test_observed_metrics_exclude_unknown_boolean_counts_and_private_text() -> None:
    scores = trial_scores(
        {
            "status": "passed",
            "cost_cny": ".25",
            "elapsed_seconds": 2.5,
            "process": {
                "tool_calls": 4,
                "duplicate_calls": None,
                "user_visible_first_errors": False,
                "recovered_without_user": 1,
            },
            "saved_constraints": {"micro_pass_rate": 0.5, "all_constraints": False},
            "memory_metrics": {
                "precision": None,
                "recall": float("nan"),
                "cross_user_leakage": False,
                "deletion_residue": False,
            },
            "text": "private body",
            "conditions": {"private": "private quote"},
        }
    )
    assert scores["v2.cost_cny"] == 0.25
    assert scores["v2.tool_calls"] == 4
    assert scores["v2.constraints_micro"] == 0.5
    assert scores["v2.all_constraints"] == 0
    assert "v2.duplicate_calls" not in scores
    assert "v2.user_visible_first_errors" not in scores
    assert "v2.memory_recall" not in scores
    assert "v2.memory_cross_user_leakage" not in scores
    assert "v2.memory_deletion_residue" not in scores
    assert "private" not in str(scores)


def test_triage_label_is_explicitly_unverified_and_unknown_step_is_omitted() -> None:
    scores = triage_scores({"reference": {"label": "wrong_tool", "first_step": 3}})
    assert scores == {
        "v2.triage_valid_output": 1.0,
        "v2.triage_wrong_tool_unverified": 1.0,
        "v2.triage_first_step_unverified": 3.0,
    }
    assert "v2.triage_first_step_unverified" not in triage_scores(
        {"reference": {"label": "unknown", "first_step": None}}
    )
    assert triage_scores({"reference": None}) == {"v2.triage_valid_output": 0.0}


def test_triage_publishes_only_failed_sources_and_cannot_swap_repeats() -> None:
    passed: dict[str, object] = {"case_id": "case", "status": "passed", "repeat": 1}
    failed: dict[str, object] = {"case_id": "case", "status": "failed", "repeat": 2}
    reference: dict[str, object] = {"case_id": "case", "trial": 2}
    assert match_triage([passed, failed], [reference]) == [(failed, reference)]
    repeated = [failed, {**failed, "repeat": 3}]
    with pytest.raises(ValueError):
        match_triage(repeated, [{**reference, "trial": 3}, reference])
    with pytest.raises(ValueError):
        match_triage(repeated, [{"case_id": "case"}, {"case_id": "case"}])
    with pytest.raises(ValueError):
        match_triage(
            [{"case_id": "case", "status": "failed"}, {"case_id": "case", "status": "failed"}],
            [{"case_id": "case"}, {"case_id": "case"}],
        )
    assert match_triage([failed], [{"case_id": "case"}]) == [(failed, {"case_id": "case"})]

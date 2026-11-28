from dataclasses import replace
from pathlib import Path

import pytest

from backend.tools.skill_config import SkillConfig
from eval.evolve.guarded import (
    Evaluation,
    GuardedEdit,
    assess,
    classify,
    evaluate_candidate,
)


def trials() -> tuple[Evaluation, ...]:
    return (
        Evaluation("c1", 1, None, frozenset({"draft"}), True, 0.0, 0.0, None, False),
        Evaluation("c2", 1, None, frozenset({"draft"}), True, 0.0, 0.0, None, False),
        Evaluation(
            "c3",
            1,
            None,
            frozenset(),
            False,
            4.0,
            0.4,
            0.8,
            True,
            frozenset({"hotel-comparison"}),
            frozenset({"hotel-comparison"}),
        ),
        Evaluation("c4", 1, None, frozenset(), False, 4.0, 0.4, 0.8, True),
    )


def improved(before: tuple[Evaluation, ...]) -> tuple[Evaluation, ...]:
    return (
        replace(before[0], violations=frozenset(), blocked=False),
        replace(before[1], violations=frozenset(), blocked=False),
        replace(before[2], score=6.0, probability=0.55, soft=0.85),
        before[3],
    )


@pytest.mark.parametrize("problem", ["target", "regression", "components", "coexistence"])
def test_each_gate_rejects_its_own_regression(problem: str) -> None:
    before = trials()
    candidate = list(improved(before))
    if problem == "target":
        candidate[1] = before[1]
    elif problem == "regression":
        candidate[2] = replace(candidate[2], blocked=True)
        candidate[3] = replace(candidate[3], blocked=True)
    elif problem == "components":
        candidate[2] = replace(candidate[2], probability=0.4, soft=0.79)
    else:
        candidate[2] = replace(candidate[2], loaded_skills=frozenset())
    result = assess(before, candidate, "draft", frozenset({"c1", "c2"}), routing_changed=True)
    assert getattr(result, problem) is False
    assert not result.passed


def test_target_requires_at_least_halving_affected_cases() -> None:
    original = trials()
    more_affected = tuple(replace(original[0], case_id=f"more-{i}") for i in range(4))
    before = (*original, *more_affected)
    gates = assess(
        before,
        (*improved(original), *more_affected),
        "draft",
        frozenset(row.case_id for row in (*original[:2], *more_affected)),
        routing_changed=True,
    )
    assert (gates.target_before, gates.target_after) == (6, 4)
    assert not gates.target
    assert gates.regression and gates.components and gates.coexistence


def test_target_cannot_replace_its_violation_with_a_new_block() -> None:
    before = trials()
    candidate = list(improved(before))
    candidate[0] = replace(candidate[0], blocked=True, violations=frozenset({"new-block"}))
    gates = assess(before, candidate, "draft", frozenset({"c1", "c2"}), routing_changed=True)
    assert (gates.target_before, gates.target_after) == (2, 0)
    assert not gates.target
    assert gates.regression and gates.components and gates.coexistence


def test_regression_requires_a_nonnegative_score_interval_upper_bound() -> None:
    before = trials()
    candidate = list(improved(before))
    candidate[2] = replace(candidate[2], score=3.0)
    candidate[3] = replace(candidate[3], score=3.0)
    gates = assess(before, candidate, "draft", frozenset({"c1", "c2"}), routing_changed=True)
    assert gates.other_pass_rate.high == 0 and gates.other_score.high < 0
    assert not gates.regression
    assert gates.target and gates.components and gates.coexistence


def test_components_require_all_applicable_soft_observations() -> None:
    original = trials()
    before = (*original[:3], replace(original[3], soft=0.05))
    candidate = list(improved(before))
    candidate[2] = replace(candidate[2], soft=0.95)
    candidate[3] = replace(candidate[3], soft=None)
    gates = assess(before, candidate, "draft", frozenset({"c1", "c2"}), routing_changed=True)
    assert gates.probability_after > gates.probability_before
    assert not gates.components
    assert gates.target and gates.regression and gates.coexistence


def test_components_reject_a_probability_loss_even_when_soft_improves() -> None:
    before = trials()
    candidate = list(improved(before))
    candidate[2] = replace(candidate[2], probability=0.35)
    gates = assess(before, candidate, "draft", frozenset({"c1", "c2"}), routing_changed=True)
    assert gates.probability_after < gates.probability_before
    assert gates.soft_after == pytest.approx(0.825) and gates.soft_before == pytest.approx(0.8)
    assert not gates.components
    assert gates.target and gates.regression and gates.coexistence


def test_comparison_rejects_mismatched_target_seeds() -> None:
    before = trials()
    candidate = list(improved(before))
    candidate[0] = replace(candidate[0], seed_id="unpaired")
    with pytest.raises(ValueError, match="种子"):
        assess(before, candidate, "draft", frozenset({"c1", "c2"}), routing_changed=False)


def test_losing_soft_coverage_does_not_improve_average() -> None:
    before = trials()
    candidate = list(improved(before))
    candidate[3] = replace(candidate[3], soft_applicable=False, soft=None)
    gates = assess(before, candidate, "draft", frozenset({"c1", "c2"}), routing_changed=False)
    assert not gates.components


def test_classification_counts_affected_cases_once_and_prioritizes_violations() -> None:
    before = trials()
    repeat = replace(before[0], repeat=2, violations=frozenset({"draft", "other"}))
    issue = classify((*before, repeat))
    assert issue is not None
    assert issue.code == "draft"
    assert issue.case_ids == ("c1", "c2")


def test_candidate_keeps_single_sentence_and_review_without_touching_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    original = source / "hotel-comparison.md"
    original.write_text("第一句。原说明。\n", encoding="utf-8")
    baseline = trials()

    def replay(directory: Path) -> tuple[Evaluation, ...]:
        assert (directory / original.name).read_text(encoding="utf-8") == "第一句。新说明。\n"
        return improved(baseline)

    pool = tmp_path / "candidates"
    config = SkillConfig(directory=source)
    result = evaluate_candidate(
        pool,
        config,
        GuardedEdit("hotel-comparison", "原说明。", "新说明。"),
        "draft",
        frozenset({"c1", "c2"}),
        baseline,
        replay,
    )
    assert result.gates.passed
    assert result.review.is_file()
    assert result.best_directory == result.directory
    assert (result.directory / "pairs.json").is_file()
    assert original.read_text(encoding="utf-8") == "第一句。原说明。\n"
    with pytest.raises(ValueError, match="一句"):
        evaluate_candidate(
            pool,
            config,
            GuardedEdit("hotel-comparison", "第一句。原说明。", "新说明。"),
            "draft",
            frozenset({"c1", "c2"}),
            baseline,
            replay,
        )

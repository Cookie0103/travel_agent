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

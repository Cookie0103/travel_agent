"""规则报告必须区分明确通过的检查和没有出现的检查。"""

from pathlib import Path

import pytest

from eval.rules import report as rule_report
from eval.rules.scenarios import Expected, Mode, observe


@pytest.mark.parametrize(
    ("rule", "code"),
    [
        (3, "recognized_constraint"),
        (4, "arrival_boundary"),
        (5, "edit_scope"),
        (6, "must_visit"),
        (7, "room_preference"),
        (13, "opening_hours"),
    ],
)
@pytest.mark.parametrize("mode", ["clear", "border"])
def test_should_pass_examples_emit_the_verified_check(rule: int, code: str, mode: Mode) -> None:
    assert observe(rule, mode, 1) == (code, "verified")


def test_rule_report_counts_a_missing_expected_check_as_a_difference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "rules.jsonl"
    rule_report.create_cases(fixture)
    cases = tuple(
        rule_report.Case.model_validate_json(line)
        for line in fixture.read_text(encoding="utf-8").splitlines()
    )
    monkeypatch.setattr(rule_report, "load_commerce_cases", lambda: ())
    _, before = rule_report.report(cases)
    assert not before["issues"]

    def without_arrival_check(rule: int, mode: Mode, variant: int) -> tuple[str, Expected]:
        if (rule, mode, variant) == (4, "clear", 1):
            return "arrival_boundary", "none"
        return observe(rule, mode, variant)

    monkeypatch.setattr(rule_report, "observe", without_arrival_check)
    markdown, after = rule_report.report(cases)
    assert after["issues"] == [
        {
            "id": "rule04-clear-1",
            "code": "arrival_boundary",
            "expected": "verified",
            "observed": "none",
        }
    ]
    assert "rule04-clear-1" in markdown

"""M4.2：分项分母、部分/未知/冲突与非法观测；不调用模型。"""

import pytest
from pydantic import ValidationError

from eval.business_metrics import BusinessMetrics, ConstraintMeasurement, business_summary
from eval.cases import Case


def measurement(status: str, **counts: object) -> dict[str, object]:
    return BusinessMetrics.model_validate(
        {"constraint": {"status": status, **counts}, "booking": "not_applicable"}
    ).model_dump(mode="json")


def test_partial_is_not_fully_verified_and_missing_candidate_stays_in_coverage() -> None:
    rows: list[dict[str, object]] = [
        {"business_metrics": measurement("complete", verified=18, unknown=0, conflict=0)},
        {"business_metrics": measurement("partial", verified=20, unknown=3, conflict=0)},
        {"business_metrics": measurement("conflict", verified=8, unknown=2, conflict=1)},
        {"business_metrics": measurement("no_candidate")},
    ]
    result = business_summary(rows)
    constraints = result["constraints"]
    assert isinstance(constraints, dict)
    assert constraints["validated_candidate_n"] == 3
    assert constraints["candidate_coverage"] == 0.75
    assert constraints["hard_constraint_pass_rate"] is None
    assert constraints["observed_hard_constraint_pass_rate"] == 1 / 3
    assert constraints["observed_candidate_no_conflict_rate"] == 2 / 3
    assert constraints["check_counts"] == {"verified": 46, "unknown": 5, "conflict": 1}
    covered = business_summary(rows[:3])["constraints"]
    assert isinstance(covered, dict) and covered["hard_constraint_pass_rate"] == 1 / 3


@pytest.mark.parametrize(
    "invalid",
    [
        {"status": "complete", "verified": 1, "unknown": 1, "conflict": 0},
        {"status": "partial", "verified": 1, "unknown": 0, "conflict": 0},
        {"status": "conflict", "verified": 1, "unknown": 0, "conflict": 0},
        {"status": "complete", "verified": 0, "unknown": 0, "conflict": 0},
        {"status": "complete", "verified": True, "unknown": 0, "conflict": 0},
        {"status": "complete", "verified": -1, "unknown": 0, "conflict": 0},
        {"status": "unavailable", "verified": 0},
        {"status": "no_candidate", "unknown": 0},
        {"status": "complete"},
    ],
)
def test_invalid_or_inconsistent_check_counts_are_rejected(invalid: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ConstraintMeasurement.model_validate(invalid)


def test_booking_safety_failures_unknown_measurements_and_recovery_remain_distinct() -> None:
    rows: list[dict[str, object]] = [
        {"business_metrics": {**measurement("not_applicable"), "booking": "correct"}},
        {"business_metrics": {**measurement("not_applicable"), "booking": "incorrect"}},
    ]
    booking = business_summary(rows)["booking"]
    assert isinstance(booking, dict) and booking["correctness_rate"] == 0.5
    rows.append({"business_metrics": {**measurement("unavailable"), "booking": "unavailable"}})
    rows.extend([{}, {"business_metrics": {"constraint": "invalid"}}])
    result = business_summary(rows)
    assert result["missing_observation_n"] == 2
    for key in ("constraints", "booking"):
        value = result[key]
        assert isinstance(value, dict) and value["applicable_n"] is None
    assert isinstance(result["booking"], dict) and result["booking"]["correctness_rate"] is None
    assert isinstance(result["recovery"], dict) and result["recovery"]["completion_rate"] is None
    assert isinstance(result["constraints"], dict)
    assert result["constraints"]["check_counts"] == {
        "verified": None,
        "unknown": None,
        "conflict": None,
    }


def test_only_explicit_frozen_business_expectations_define_applicability() -> None:
    case = Case(case_id="scope", source="self-authored", adaptation="mechanism", input="恢复")
    unscoped = BusinessMetrics.for_case(case)
    assert unscoped.constraint.status == "not_applicable" and unscoped.booking == "not_applicable"
    fault = case.model_copy(update={"business_checks": ("expected_tool_failure",)})
    assert BusinessMetrics.for_case(fault).booking == "not_applicable"
    held_fault = fault.model_copy(update={"required_tools": ["hold_hotel"]})
    assert BusinessMetrics.for_case(held_fault).booking == "unavailable"
    assert BusinessMetrics.for_case(held_fault).recovery == "unmeasured"

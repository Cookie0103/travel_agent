"""模拟评测交付/约束/成本分母独立；缺观测不能被总成功率覆盖。"""

import pytest

from eval.report import simulation_summary


def test_saved_constraint_micro_macro_and_delivery_remain_separate() -> None:
    rows: list[dict[str, object]] = []
    for trial in range(1, 4):
        rows.append(
            {
                "case_id": "v2-user-three-segments",
                "trial": trial,
                "status": "passed" if trial < 3 else "failed",
                "cost_cny": "1",
                "elapsed_seconds": 2.0,
                "process": {
                    "tool_calls": 2,
                    "duplicate_calls": None,
                    "recovered_without_user": 0,
                    "user_visible_first_errors": 0,
                    "user_visible_errors": 0,
                },
                "saved_constraints": {
                    "delivered": trial < 3,
                    "checks": [
                        {"passed": True, "status": "verified"},
                        {"passed": False, "status": "unknown"},
                    ]
                    if trial < 3
                    else [],
                    "all_constraints": False if trial < 3 else None,
                },
            }
        )
    result = simulation_summary(rows, 3)
    constraints, cost, reliability, process = (
        result["saved_constraints"],
        result["original_currency_cost"],
        result["reliability"],
        result["process"],
    )
    assert isinstance(constraints, dict) and isinstance(cost, dict)
    assert isinstance(reliability, dict) and isinstance(process, dict)
    assert constraints["delivery_rate"] == pytest.approx(2 / 3)
    assert constraints["micro"] == 0.5
    assert constraints["macro"] == 0.5
    assert constraints["all_constraints_rate"] == 0
    assert cost["cost_per_success"] == "1.5"
    assert reliability["pass_at_k"] == 1
    assert reliability["pass_power_k"] == 0
    assert process["duplicate_calls"] is None


def test_unobserved_constraints_cost_and_process_remain_unknown() -> None:
    result = simulation_summary(
        [{"case_id": "v2-user-three-segments", "trial": 1, "status": "error"}], 3
    )
    constraints, cost, reliability, process = (
        result["saved_constraints"],
        result["original_currency_cost"],
        result["reliability"],
        result["process"],
    )
    assert isinstance(constraints, dict) and isinstance(cost, dict)
    assert isinstance(reliability, dict) and isinstance(process, dict)
    assert constraints["micro"] is None
    assert constraints["delivery_rate"] is None
    assert cost["total"] is None
    assert process["user_visible_first_errors"] is None
    assert reliability["pass_at_k"] is None

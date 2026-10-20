"""业务分项观测与汇总；保留候选覆盖率和未知，不从规则总分反推业务质量。"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eval.cases import Case

PLAN_CHECKS = frozenset({"plan_draft", "one_item_patch", "second_afternoon_shift"})
BOOKING_CHECKS = frozenset({"booking_held", "booking_unknown_preserved"})


class ConstraintMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal[
        "not_applicable", "unavailable", "no_candidate", "complete", "partial", "conflict"
    ]
    verified: int | None = Field(default=None, strict=True, ge=0)
    unknown: int | None = Field(default=None, strict=True, ge=0)
    conflict: int | None = Field(default=None, strict=True, ge=0)

    @model_validator(mode="after")
    def consistent(self) -> "ConstraintMeasurement":
        measured = self.status in {"complete", "partial", "conflict"}
        counts = (self.verified, self.unknown, self.conflict)
        if not measured and any(v is not None for v in counts):
            raise ValueError("未校验候选不能有检查计数")
        if measured and (any(v is None for v in counts) or not any(counts)):
            raise ValueError("已校验候选需要检查计数")
        if (
            (self.status == "complete" and (self.unknown or self.conflict))
            or (self.status == "partial" and (not self.unknown or self.conflict))
            or (self.status == "conflict" and not self.conflict)
        ):
            raise ValueError("校验状态与完整检查计数不符")
        return self


class BusinessMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    constraint: ConstraintMeasurement
    booking: Literal["not_applicable", "unavailable", "correct", "incorrect"]
    # 当前冻结套件没有恢复目标/恢复动作；错误解释不等于恢复。
    recovery: Literal["unmeasured"] = "unmeasured"

    @classmethod
    def for_case(cls, case: Case) -> "BusinessMetrics":
        booking = bool(BOOKING_CHECKS.intersection(case.business_checks)) or (
            "hold_hotel" in case.required_tools and "expected_tool_failure" in case.business_checks
        )
        return cls(
            constraint=ConstraintMeasurement(
                status="unavailable"
                if PLAN_CHECKS.intersection(case.business_checks)
                else "not_applicable"
            ),
            booking="unavailable" if booking else "not_applicable",
        )


@dataclass(frozen=True)
class BusinessAssessment:
    checks: dict[str, bool]
    metrics: BusinessMetrics


def business_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    values: list[BusinessMetrics] = []
    for row in rows:
        raw = row.get("business_metrics")
        if raw is None:
            continue
        try:
            values.append(BusinessMetrics.model_validate(raw))
        except ValidationError:
            continue  # 非法/旧记录缺观测：保留unknown，不能推断成功或适用范围。
    missing = len(rows) - len(values)
    constraints = [v.constraint for v in values if v.constraint.status != "not_applicable"]
    candidates = [v for v in constraints if v.status in {"complete", "partial", "conflict"}]
    states = {
        state: sum(v.status == state for v in constraints)
        for state in ("complete", "partial", "conflict", "no_candidate", "unavailable")
    }
    passed = sum(v.status == "complete" for v in candidates)
    covered = bool(candidates) and len(candidates) == len(constraints) and not missing
    bookings = [v.booking for v in values if v.booking != "not_applicable"]
    measured_bookings = [v for v in bookings if v in {"correct", "incorrect"}]
    return {
        "version": 1,
        "records": len(rows),
        "missing_observation_n": missing,
        "constraints": {
            "applicable_n": len(constraints) if not missing else None,
            "observed_applicable_n": len(constraints),
            "validated_candidate_n": len(candidates),
            "states": states,
            "check_counts": {
                name: sum(getattr(v, name) or 0 for v in candidates) if candidates else None
                for name in ("verified", "unknown", "conflict")
            },
            "candidate_coverage": len(candidates) / len(constraints)
            if constraints and not missing
            else None,
            "observed_hard_constraint_pass_rate": passed / len(candidates) if candidates else None,
            "hard_constraint_pass_rate": passed / len(candidates) if covered else None,
            "observed_candidate_no_conflict_rate": sum(v.status != "conflict" for v in candidates)
            / len(candidates)
            if candidates
            else None,
            "scope": "本轮最新草稿按当前条件重新校验；partial仍有unknown，非全部条件确定满足",
        },
        "booking": {
            "applicable_n": len(bookings) if not missing else None,
            "observed_applicable_n": len(bookings),
            "measured_n": len(measured_bookings),
            "correct_n": measured_bookings.count("correct"),
            "incorrect_n": measured_bookings.count("incorrect"),
            "unavailable_n": bookings.count("unavailable"),
            "correctness_rate": measured_bookings.count("correct") / len(measured_bookings)
            if measured_bookings and len(measured_bookings) == len(bookings) and not missing
            else None,
            "scope": "模拟暂留/unknown保留/预期供应商故障及无新增订单；不测完整付款下单",
        },
        "recovery": {
            "completion_rate": None,
            "measured_n": 0,
            "reason": "冻结套件未执行带原始目标的故障恢复；不能从故障解释推断恢复成功",
        },
    }

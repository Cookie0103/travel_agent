"""行程校验级别：业务与 v3 评测共用代码登记。"""

from typing import Literal

from backend.domain.itinerary import CheckStatus

type ValidationLevel = Literal["block", "warning", "note"]

VALIDATION_LEVELS: dict[str, ValidationLevel] = {
    **{
        code: "block"
        for code in (
            "arrival_boundary",
            "city",
            "currency",
            "departure_boundary",
            "edit_scope",
            "hotel_source",
            "hotel_stay_scope",
            "must_visit",
            "place_source",
            "opening_hours",
            "rain_plan_required",
            "room_preference",
            "trip_dates",
        )
    },
    **{
        code: "warning"
        for code in (
            "budget_missing",
            "child_day_limits",
            "daily_hours",
            "daily_movement",
            "day_backtrack",
            "day_gap",
            "departure_time",
            "estimated_cost_over_budget",
            "free_text_constraints",
            "hotel_missing",
            "hotel_over_budget_unaccepted",
            "hotel_over_nightly_budget",
            "hotel_return",
            "hotel_change_luggage",
            "hotel_stay_time",
            "hotel_stay_missing",
            "hotel_stay_skipped",
            "hotel_total",
            "known_cost_over_budget",
            "lodging_budget_conflict",
            "lodging_budget_unknown",
            "lodging_budget_warning",
            "lodging_budget_within",
            "meal_time",
            "other_costs",
            "overlap",
            "pace_too_sparse",
            "pace_warning",
            "rain_plan",
            "repeated_place_warning",
            "route_departure",
            "route_duration",
            "route_estimate",
            "route_fare",
            "route_gap",
            "route_live",
            "route_missing",
            "route_scope",
            "route_source",
            "route_unexpected",
            "visit_duration",
            "visit_duration_range",
            "travel_peak",
        )
    },
    "recognized_constraint": "note",
    "reservation_required": "note",
}


def rule_status(code: str, passed: bool) -> CheckStatus:
    if passed:
        return "verified"
    return "conflict" if VALIDATION_LEVELS[code] == "block" else "unknown"

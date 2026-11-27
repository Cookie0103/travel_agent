"""validator code的自动分级表；独立成模块，供题库加载器与评分共用（避免循环导入）。"""

from typing import Literal

type Tier = Literal["hard", "soft"]

# validator各code的自动分级。HARD=事实性硬错（日期/住宿段/币种/来源/城市）；conflict即硬失败。
# 其余为SOFT：不影响success，只降低soft_score。新增validator code必须在此登记（测试强制）。
VALIDATOR_TIER: dict[str, Tier] = {
    "trip_dates": "hard",
    "hotel_stay_scope": "hard",
    "currency": "hard",
    "place_source": "hard",
    "hotel_source": "hard",
    "city": "hard",
    **{
        code: "soft"
        for code in (
            "budget_missing",
            "day_gap",
            "departure_time",
            "estimated_cost_over_budget",
            "free_text_constraints",
            "hotel_missing",
            "hotel_over_budget_unaccepted",
            "hotel_over_nightly_budget",
            "hotel_total",
            "known_cost_over_budget",
            "meal_time",
            "opening_hours",
            "other_costs",
            "overlap",
            "pace_too_sparse",
            "pace_warning",
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
        )
    },
}
DEFAULT_TIER: Tier = "soft"  # 表外的新code不应静默变硬；测试会提示补登记

"""开发期限额档位；relaxed 只放宽次数与时限，费用授权/预算上限不在此处。"""

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    max_calls: int
    max_turns: int
    max_attempts: int
    worker_timeout: float
    process_timeout: float
    run_timeout: float
    max_output: int
    run_caps: Mapping[str, int]  # 每个run的外部API次数
    daily_defaults: Mapping[str, int]  # 环境变量未设置时的每日上限


DEFAULT = Limits(
    16, 12, 12, 115, 120, 150.0, 2048,
    {"geocode": 2, "places": 3, "routes": 12, "rakuten": 8, "weather": 1},
    {"geocode": 50, "places": 25, "routes": 150, "rakuten": 150, "weather": 200},
)  # fmt: skip
RELAXED = Limits(
    40, 30, 30, 280, 290, 300.0, 4096,
    {"geocode": 5, "places": 15, "routes": 40, "rakuten": 20, "weather": 2},
    {"geocode": 100, "places": 150, "routes": 400, "rakuten": 300, "weather": 300},
)  # fmt: skip


def current(env: Mapping[str, str] = os.environ) -> Limits:
    return RELAXED if env.get("TRAVEL_PROFILE") == "relaxed" else DEFAULT

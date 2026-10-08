"""开发期限额档位；relaxed/human 只放宽次数与时限，费用授权/预算上限不在此处。"""

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    max_calls: int
    max_turns: int
    max_attempts: int
    upstream_timeout: float
    worker_timeout: float
    process_timeout: float
    run_timeout: float
    max_output: int
    run_caps: Mapping[str, int]  # 每个run的外部API次数
    daily_defaults: Mapping[str, int]  # 环境变量未设置时的每日上限
    first_byte_timeout: float = 0.0  # 秒；0=关闭。仅在尚无任何响应头时触发
    daily_cny_cap: bool = True  # False=不施加每日CNY上限(仅HUMAN)；账本预占/结算照常记录
    upstream_retries: int = 0  # 首字节停滞后的重试次数（每次独立预占并计入attempts）
    evidence_ttl_minutes: int = 15  # 酒店报价与路线估算证据的有效分钟数（地点/文章另计）
    max_validations: int = 4  # 首次校验+修复轮次总数；评测单因素变体另固定为1

    @property
    def request_worst_case(self) -> float:
        """一次受守卫请求的最长耗时：各次停滞重试 + 最后一次完整期限。"""
        return self.upstream_timeout + self.upstream_retries * self.first_byte_timeout


DEFAULT = Limits(
    16, 12, 12, 90, 210, 220, 240.0, 2048,
    {"geocode": 2, "places": 3, "routes": 12, "rakuten": 8, "weather": 1},
    {"geocode": 50, "places": 25, "routes": 150, "rakuten": 150, "weather": 200},
)  # fmt: skip
RELAXED = Limits(
    40, 30, 30, 120, 280, 290, 300.0, 4096,
    {"geocode": 5, "places": 15, "routes": 40, "rakuten": 20, "weather": 2},
    {"geocode": 100, "places": 150, "routes": 400, "rakuten": 300, "weather": 300},
)  # fmt: skip
HUMAN = Limits(
    80, 60, 40, 120, 840, 850, 900.0, 8192,
    {"geocode": 10, "places": 60, "routes": 80, "rakuten": 30, "weather": 5},
    {"geocode": 100, "places": 300, "routes": 600, "rakuten": 300, "weather": 300},
    first_byte_timeout=25.0, upstream_retries=2, daily_cny_cap=False,
    evidence_ttl_minutes=30, max_validations=50,
)  # fmt: skip
PROFILES = {"relaxed": RELAXED, "human": HUMAN}  # 人工手测用human；机器/评测保持default


def current(env: Mapping[str, str] = os.environ) -> Limits:
    return PROFILES.get(env.get("TRAVEL_PROFILE", ""), DEFAULT)


def profile_name(env: Mapping[str, str] = os.environ) -> str:
    return next((name for name, limits in PROFILES.items() if limits is current(env)), "default")

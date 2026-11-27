"""从业务校验级别派生 v3 兼容的 hard/soft 评分级别。"""

from typing import Literal

from backend.domain.validation_levels import VALIDATION_LEVELS

type Tier = Literal["hard", "soft"]

VALIDATOR_TIER: dict[str, Tier] = {
    code: "hard" if level == "block" else "soft" for code, level in VALIDATION_LEVELS.items()
}
DEFAULT_TIER: Tier = "soft"  # 兼容已保存的早期校验结果。

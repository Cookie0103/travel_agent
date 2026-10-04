"""读取协议探针配置；在构造 SDK 之前拒绝缺密钥或非法预算。"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal

Currency = Literal["CNY", "USD"]
Provider = Literal["deepseek", "anthropic"]
BASE_URL = "https://api.deepseek.com/anthropic"
MAX_TOKENS = 1024
MAX_REQUEST_BYTES = 8192


class ProbeError(RuntimeError):
    """仅携带预先定义的安全说明，不转发 SDK 原始异常。"""

    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        super().__init__(f"{code}: {reason}")


@dataclass(frozen=True)
class Settings:
    """本次探针的私有配置，密钥不参与 repr。"""

    api_key: str = field(repr=False)
    model: str
    cny_limit: Decimal
    usd_limit: Decimal
    provider: Provider = "deepseek"

    @property
    def currency(self) -> Currency:
        return "CNY" if self.provider == "deepseek" else "USD"

    @property
    def daily_limit(self) -> Decimal:
        return self.cny_limit if self.currency == "CNY" else self.usd_limit


@dataclass(frozen=True)
class Price:
    """2026-10-03官方价表；原币种/百万token，缓存未知时使用保守上界。"""

    input_per_million: Decimal
    output_per_million: Decimal
    attempt_charge: Decimal
    input_limit: int = 1_048_576
    cache_write_multiplier: Decimal = Decimal(1)
    currency: Currency = "CNY"

    def usage_upper(self, inputs: int, outputs: int) -> Decimal:
        if inputs < 0 or outputs < 0:
            raise ProbeError("provider_error", "响应中的 token 数不能为负")
        return (inputs * self.input_per_million + outputs * self.output_per_million) / 1_000_000


def price_for(model: str) -> Price:
    """拒绝未知/映射模型名，避免换模型后仍套用原来的单价。"""
    prices = {
        "deepseek-flash": Price(Decimal("2"), Decimal("8"), Decimal("0.05")),
        "deepseek-v4-pro": Price(Decimal("9"), Decimal("27"), Decimal("0.20")),
        "claude-haiku-4-5-20251001": Price(
            Decimal("1"), Decimal("5"), Decimal("0.01"), 200_000, Decimal(2), "USD"
        ),
    }
    if model not in prices:
        raise ProbeError("validation", "DEEPSEEK_MODEL/ANTHROPIC_MODEL缺失或未配置对应计价规则")
    return prices[model]


def read_budget(value: str) -> Decimal:
    """金额只能是有限非负十进制数，不打印错误输入。"""
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ProbeError("validation", "预算缺失或不是有效数值") from None
    if not amount.is_finite() or amount < 0:
        raise ProbeError("validation", "预算必须是有限非负数")
    return amount


def load_settings(environment: Mapping[str, str]) -> Settings:
    """只允许从环境获取密钥；无关线路不影响 CNY 的计费归属。"""
    key = environment.get("DEEPSEEK_API_KEY", "").strip()
    if not key or key in {"你的真实密钥", "你的密钥"}:
        raise ProbeError("validation", "未配置 DeepSeek API Key")
    model = environment.get("DEEPSEEK_MODEL", "").strip()
    if not model.startswith("deepseek-"):
        raise ProbeError("validation", "DEEPSEEK_MODEL必须使用已配置的DeepSeek模型")
    price_for(model)
    cny = read_budget(environment.get("DAILY_BUDGET_CNY", ""))
    usd = read_budget(environment.get("DAILY_BUDGET_USD", "") or "0")
    if cny == 0:
        raise ProbeError("blocked", "人民币线路已禁用")
    return Settings(key, model, cny, usd)

"""SDK供应商显式选择；配置日预算不等于获得真实调用授权。"""

from collections.abc import Mapping

from backend.limits import (
    ProbeError,
    Provider,
    Settings,
    load_settings,
    price_for,
    read_budget,
)


def provider_name(environment: Mapping[str, str]) -> Provider:
    value = environment.get("LLM_PROVIDER", "deepseek").strip()
    if value not in {"deepseek", "anthropic"}:
        raise ProbeError("validation", "LLM_PROVIDER仅支持deepseek或anthropic")
    return "deepseek" if value == "deepseek" else "anthropic"


def model_name(environment: Mapping[str, str], provider: Provider) -> str:
    key = "DEEPSEEK_MODEL" if provider == "deepseek" else "ANTHROPIC_MODEL"
    return environment.get(key, "").strip() or "unconfigured"


def load_runtime_settings(environment: Mapping[str, str]) -> Settings:
    provider = provider_name(environment)
    if provider == "deepseek":
        return load_settings(environment)
    key = environment.get("ANTHROPIC_API_KEY", "").strip()
    if not key or key in {"你的真实密钥", "你的密钥"}:
        raise ProbeError("validation", "未配置Anthropic API Key")
    model = model_name(environment, provider)
    if not model.startswith("claude-"):
        raise ProbeError("validation", "Anthropic线路必须使用已配置的Claude模型")
    price_for(model)
    usd = read_budget(environment.get("DAILY_BUDGET_USD", "") or "0")
    if usd == 0:
        raise ProbeError("blocked", "美元线路已禁用")
    return Settings(
        key, model, read_budget(environment.get("DAILY_BUDGET_CNY", "") or "0"), usd, provider
    )

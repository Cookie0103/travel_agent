"""模型选择器配置视图；只检查配置，不发出网络请求。"""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel

from backend.limits import ProbeError
from backend.providers.claude_agent.budget import check_authorization
from backend.providers.claude_agent.settings import load_runtime_settings


class ModelOption(BaseModel):
    id: Literal["offline", "deepseek", "claude"]
    label: str
    available: bool
    reason: str | None = None


def model_options(environment: Mapping[str, str], live_enabled: bool) -> list[ModelOption]:
    options = [ModelOption(id="offline", label="离线演示", available=True)]
    for identifier, provider in (("deepseek", "deepseek"), ("claude", "anthropic")):
        reason = None
        if not live_enabled:
            reason = "服务未以 --live 启动"
        else:
            try:
                settings = load_runtime_settings({**environment, "LLM_PROVIDER": provider})
                check_authorization(settings.currency)
            except ProbeError as error:
                reason = str(error)
        options.append(
            ModelOption(
                id="deepseek" if identifier == "deepseek" else "claude",
                label="DeepSeek" if identifier == "deepseek" else "Claude",
                available=reason is None,
                reason=reason,
            )
        )
    return options

"""验证 SDK 出站 JSON 的可计费范围；守卫不猜测未知功能的费用。"""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from backend.providers.claude_agent.limits import ProbeError, price_for
from backend.providers.claude_agent.profile import current

MAX_BYTES = 131072
MAX_INPUT_TOKENS = 1_048_576
TOOL_NAME = "mcp__probe__echo"


@dataclass(frozen=True)
class Request:
    """只保留已验证的转发字节和预占金额。"""

    body: bytes
    charge: Decimal
    max_output: int
    temperature: Literal[0] | None = None


def validate_request(
    body: bytes,
    model: str,
    allowed_tools: frozenset[str] = frozenset({TOOL_NAME}),
    *,
    temperature: Literal[0] | None = None,
) -> Request:
    if len(body) > MAX_BYTES:
        raise ProbeError("blocked", "SDK 输入超过接入实验上限")
    try:
        raw: object = json.loads(body)
    except (ValueError, UnicodeError):
        raise ProbeError("validation", "SDK 请求不是有效 JSON") from None
    if not isinstance(raw, dict) or raw.get("model") != model:
        raise ProbeError("blocked", "SDK 尝试使用未授权模型")
    allowed = {
        "model",
        "max_tokens",
        "messages",
        "system",
        "tools",
        "tool_choice",
        "stream",
        "temperature",
        "top_p",
        "top_k",
        "stop_sequences",
        "metadata",
        "thinking",
        "output_config",
        "context_management",
    }
    if set(raw) - allowed:
        raise ProbeError("blocked", "SDK 请求含尚未验证的协议功能")
    output = raw.get("max_tokens")
    if type(output) is not int or not 1 <= output <= current().max_output:
        raise ProbeError("blocked", "SDK 输出超过接入实验上限")
    if raw.get("stream") is not True:
        raise ProbeError("validation", "接入实验仅接受流式 Messages")
    tools = raw.get("tools", [])
    if not isinstance(tools, list) or len(tools) != len(allowed_tools):
        raise ProbeError("blocked", "SDK 工具集合与本轮允许集合不一致")
    names = [item.get("name") for item in tools if isinstance(item, dict)]
    if not all(isinstance(name, str) for name in names) or set(names) != allowed_tools:
        raise ProbeError("blocked", "SDK 试图使用未授权工具")
    _check_blocks(raw)
    if temperature is not None:
        if (
            type(temperature) is not int
            or temperature != 0
            or not model.startswith("deepseek-")
            or allowed_tools
            or ("thinking" in raw and raw["thinking"] != {"type": "disabled"})
            or any(raw.get(key) is not None for key in ("top_p", "top_k"))
        ):
            raise ProbeError("blocked", "固定温度评审只支持无工具且关闭思考的DeepSeek")
        raw["temperature"] = 0
        # 锁定CLI省略disabled字段；评审在实际转发层显式关闭思考以使温度生效。
        raw["thinking"] = {"type": "disabled"}
        body = json.dumps(raw, ensure_ascii=False).encode("utf-8")
        if len(body) > MAX_BYTES:
            raise ProbeError("blocked", "SDK 输入超过接入实验上限")
    price = price_for(model)
    # 不变量：按模型整个上下文与最高缓存写价预占，不猜文本字节/token比例。
    charge = price.usage_upper(int(price.input_limit * price.cache_write_multiplier), output)
    return Request(body, charge, output, temperature)


def _check_blocks(value: object, depth: int = 0) -> None:
    if depth > 30:
        raise ProbeError("validation", "SDK 请求嵌套过深")
    if isinstance(value, dict):
        kind = value.get("type")
        if kind in {"image", "document", "url", "base64", "server_tool_use"}:
            raise ProbeError("blocked", "接入实验不接收多媒体或服务器工具")
        if isinstance(kind, str) and (kind.startswith("web_") or kind.startswith("computer_")):
            raise ProbeError("blocked", "接入实验禁止服务器工具")
        for item in value.values():
            _check_blocks(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_blocks(item, depth + 1)

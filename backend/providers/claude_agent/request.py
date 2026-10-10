"""验证 SDK 出站 JSON 的可计费范围；守卫不猜测未知功能的费用。"""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from backend.limits import ProbeError, price_for
from backend.profile import current

MAX_BYTES = 128 * 1024
DEEPSEEK_MAX_BYTES = 512 * 1024
MAX_INPUT_TOKENS = 1_048_576
TOOL_NAME = "mcp__probe__echo"
# 预占输入token上界 = 请求体UTF-8字节数 * 5/4 + 固定开销。任何分词器每token至少1字节，
# 转义后的多字节JSON文本字节数仍不小于token数；x1.25与固定1024覆盖上游把tools/system
# 渲染进聊天模板时额外增加的文本。DeepSeek思考已被强制关闭且max_tokens含思考token。
INPUT_MARGIN_NUM, INPUT_MARGIN_DEN, INPUT_OVERHEAD_TOKENS = 5, 4, 1024


def request_byte_limit(model: str) -> int:
    """DeepSeek 规划需要更多工具上下文；其他线路保留原预算验证边界。"""
    return DEEPSEEK_MAX_BYTES if model.startswith("deepseek-") else MAX_BYTES


class RequestTooLarge(ProbeError):
    """携带可安全记录的大小，区分 SDK 原请求与协议规范化后的请求。"""

    def __init__(self, size: int, limit: int, phase: Literal["ingress", "normalized"]) -> None:
        self.size, self.limit, self.phase = size, limit, phase
        super().__init__("blocked", f"SDK 请求超过本地字节上限（{size} > {limit}）")


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
    limit = request_byte_limit(model)
    if len(body) > limit:
        raise RequestTooLarge(len(body), limit, "ingress")
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
    if model.startswith("deepseek-"):
        # CLI对未知模型省略disabled且仍传high；落实SDK已选择的非思考模式。
        if "thinking" in raw and raw["thinking"] != {"type": "disabled"}:
            raise ProbeError("blocked", "DeepSeek接入仅允许已配置的非思考模式")
        raw["thinking"] = {"type": "disabled"}
        config = raw.get("output_config")
        if config is not None:
            if not isinstance(config, dict):
                raise ProbeError("validation", "输出配置必须为对象")
            config = {key: value for key, value in config.items() if key != "effort"}
            if config:
                raw["output_config"] = config
            else:
                raw.pop("output_config", None)
    if temperature is not None or model.startswith("deepseek-"):
        body = json.dumps(raw, ensure_ascii=False).encode("utf-8")
        if len(body) > limit:
            raise RequestTooLarge(len(body), limit, "normalized")
    price = price_for(model)
    # 不变量：预占=该请求可能的最大费用（输入token<=字节上界，按最高输入价即
    # 未命中价*缓存写倍数；输出<=max_tokens）。无结算的尝试仍按此全额计费。
    # 单价只有一档未命中价（缓存读更便宜），故以其为最高价。
    inputs = min(
        len(body) * INPUT_MARGIN_NUM // INPUT_MARGIN_DEN + INPUT_OVERHEAD_TOKENS,
        price.input_limit,
    )
    charge = price.usage_upper(int(inputs * price.cache_write_multiplier), output)
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

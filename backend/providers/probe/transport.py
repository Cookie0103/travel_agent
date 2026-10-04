"""DeepSeek SDK 边界：固定目标、禁重试、计费前置、流式结构摘要。"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from anthropic import (
    Anthropic,
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    DefaultHttpxClient,
)
from anthropic.types import Message, MessageParam, TextBlock, ThinkingBlock, ToolParam, ToolUseBlock

from backend.providers.probe.ledger import Ledger
from backend.providers.probe.settings import (
    BASE_URL,
    MAX_REQUEST_BYTES,
    MAX_TOKENS,
    ProbeError,
    Settings,
    price_for,
)


@dataclass(frozen=True, repr=False)
class Reply:
    """完整消息仅供内存续接；报告只能使用 summary。"""

    message: Message
    events: tuple[str, ...]

    def summary(self, model_requested: str) -> dict[str, object]:
        usage = self.message.usage
        inputs = usage.input_tokens + (usage.cache_read_input_tokens or 0)
        inputs += usage.cache_creation_input_tokens or 0
        estimate = price_for(model_requested).usage_upper(inputs, usage.output_tokens)
        return {
            "model": self.message.model,
            "stop_reason": self.message.stop_reason,
            "content_types": [block.type for block in self.message.content],
            "events": list(self.events),
            "input_tokens": inputs,
            "output_tokens": usage.output_tokens,
            "usage_cost_upper_cny": str(estimate),
        }


def create_client(
    settings: Settings, *, http_client: DefaultHttpxClient | None = None
) -> Anthropic:
    """固定官方域名；兼容 SDK 不会读取美元线路的 API Key。"""
    for name in ("anthropic", "httpx2", "httpcore2"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return Anthropic(
        api_key=settings.api_key,
        base_url=BASE_URL,
        max_retries=0,
        timeout=45.0,
        http_client=http_client or DefaultHttpxClient(follow_redirects=False, trust_env=False),
    )


def request(
    client: Anthropic,
    ledger: Ledger,
    settings: Settings,
    messages: list[MessageParam],
    tools: list[ToolParam],
) -> Reply:
    """最多一次 HTTP 尝试；错误返回安全分类，绝不输出异常原文。"""
    body = json.dumps({"messages": messages, "tools": tools}, default=_serialize_block)
    if len(body.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ProbeError("blocked", "请求超过本探针输入长度上限")
    ledger.charge(
        "CNY", price_for(settings.model).attempt_charge, settings.cny_limit, datetime.now(UTC)
    )
    try:
        with client.messages.stream(
            model=settings.model,
            max_tokens=MAX_TOKENS,
            messages=messages,
            tools=tools,
            thinking={"type": "enabled", "budget_tokens": 512},
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
        ) as stream:
            events = tuple(dict.fromkeys(event.type for event in stream))
            if "message_stop" not in events:
                raise ProbeError("provider_error", "流提前中断，不返回半个消息")
            return Reply(stream.get_final_message(), events)
    except APITimeoutError:
        raise ProbeError("timeout", "模型请求超时，已计次且不自动重试") from None
    except APIStatusError as error:
        code = "rate_limited" if error.status_code == 429 else "provider_error"
        raise ProbeError(code, f"HTTP {error.status_code}，已计次且不自动重试") from None
    except APIConnectionError:
        raise ProbeError("unavailable", "无法连接 DeepSeek，已计次") from None
    except APIError:
        raise ProbeError("provider_error", "SDK 拒绝响应，不记录原始错误正文") from None
    except (ValueError, RuntimeError):
        raise ProbeError("provider_error", "流未完成或 SDK 无法解析响应") from None


def _serialize_block(value: object) -> object:
    """只支持 SDK 内容块的 JSON 序列化，不使用宽泛对象 repr。"""
    if isinstance(value, (TextBlock, ThinkingBlock, ToolUseBlock)):
        return value.model_dump(mode="json")
    raise ProbeError("validation", "请求包含无法序列化的对象")

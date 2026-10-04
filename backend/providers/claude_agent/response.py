"""解析完整 SSE 的费用摘要，缺最终 usage 或重复终止时拒绝退款。"""

import json

from backend.providers.claude_agent.limits import Currency, ProbeError, price_for
from backend.providers.claude_agent.request import Request


def summarize(
    content: bytes, request: Request, model: str, currency: Currency = "CNY"
) -> dict[str, object]:
    try:
        events = _events(content)
        kinds = [e.get("type") for e in events]
        if (
            kinds.count("message_start") != 1
            or kinds.count("message_stop") != 1
            or kinds.count("message_delta") != 1
            or kinds[0] != "message_start"
            or kinds[-1] != "message_stop"
            or kinds[-2] != "message_delta"
            or "error" in kinds
        ):
            raise ValueError
        tools = _check_blocks(events[1:-2])
        start = events[0]["message"]
        end = next(e for e in events if e.get("type") == "message_delta")
        if not isinstance(start, dict) or start.get("model") != model:
            raise ValueError
        delta = end.get("delta")
        if not isinstance(delta, dict) or delta.get("stop_reason") not in {
            "end_turn",
            "tool_use",
            "max_tokens",
            "stop_sequence",
        }:
            raise ValueError
        initial, final = start.get("usage"), end.get("usage")
        if not isinstance(initial, dict) or not isinstance(final, dict):
            raise ValueError
        tokens = _tokens(initial, final)
    except (ValueError, TypeError, KeyError, StopIteration, UnicodeError, IndexError):
        raise ProbeError("provider_error", "上游 SSE 或最终 usage 不完整，保留全部预占") from None
    inputs = sum(v for k, v in tokens.items() if k != "output_tokens")
    price = price_for(model)
    if currency != price.currency:
        raise ProbeError("blocked", "响应费用币种与模型不一致")
    if inputs > price.input_limit:
        raise ProbeError("blocked", "上游输入超出模型上下文上界")
    # 无缓存TTL明细时，Claude写缓存统一按更高的1小时价格保守结算。
    weighted_inputs = inputs + int(
        tokens["cache_creation_input_tokens"] * (price.cache_write_multiplier - 1)
    )
    estimate = price.usage_upper(weighted_inputs, tokens["output_tokens"])
    if estimate > request.charge or tokens["output_tokens"] > request.max_output:
        raise ProbeError("blocked", "上游 usage 超出预占上界，停止后续请求")
    result: dict[str, object] = {
        "model": model,
        "stop_reason": delta["stop_reason"],
        "tool_names": sorted(tools),
        "events": sorted({str(k) for k in kinds}),
        **tokens,
        "currency": currency,
        "usage_cost_upper": str(estimate),
        "reserved": str(request.charge),
    }
    if currency == "CNY":
        result.update(usage_cost_upper_cny=str(estimate), reserved_cny=str(request.charge))
    if request.temperature is not None:
        result["temperature"] = request.temperature
    return result


def _events(content: bytes) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in content.decode("utf-8").splitlines():
        if not line.startswith("data:"):
            continue
        event: object = json.loads(line[5:])
        if not isinstance(event, dict):
            raise ValueError
        if event.get("type") != "ping":
            events.append({str(k): v for k, v in event.items()})
    return events


def _tokens(initial: dict[str, object], final: dict[str, object]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key in (
        "input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "output_tokens",
    ):
        value = (
            final.get(key)
            if key == "output_tokens"
            else initial.get(key, 0 if "cache" in key else None)
        )
        if type(value) is not int or value < 0:
            raise ValueError
        result[key] = value
    initial_output = initial.get("output_tokens")
    if type(initial_output) is not int or not 0 <= initial_output <= result["output_tokens"]:
        raise ValueError
    for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        if key in final:
            value = final[key]
            if type(value) is not int or value < result[key]:
                raise ValueError
            result[key] = value
    return result


def _check_blocks(events: list[dict[str, object]]) -> set[str]:
    opened: set[int] = set()
    seen: set[int] = set()
    tools: set[str] = set()
    for event in events:
        kind, index = event.get("type"), event.get("index")
        if type(index) is not int or index < 0:
            raise ValueError
        if kind == "content_block_start" and index not in seen:
            block = event.get("content_block")
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name")
                if not isinstance(name, str) or not name:
                    raise ValueError
                tools.add(name)
            opened.add(index)
            seen.add(index)
        elif kind == "content_block_delta" and index in opened:
            continue
        elif kind == "content_block_stop" and index in opened:
            opened.remove(index)
        else:
            raise ValueError
    if opened:
        raise ValueError
    return tools

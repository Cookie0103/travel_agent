"""测试共用：模型 HTTP 请求/响应的最小合法报文。"""

import json

from backend.providers.claude_agent.request import TOOL_NAME


def request_body(**changes: object) -> bytes:
    data = {
        "model": "deepseek-flash",
        "max_tokens": 1024,
        "stream": True,
        "tools": [{"name": TOOL_NAME, "input_schema": {"type": "object"}}],
        "messages": [{"role": "user", "content": "test"}],
    }
    data.update(changes)
    return json.dumps(data).encode()


def response_body(**changes: object) -> bytes:
    message: dict[str, object] = {
        "model": "deepseek-flash",
        "usage": {"input_tokens": 100, "output_tokens": 0},
    }
    message.update(changes)
    frames = [
        {"type": "message_start", "message": message},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 20},
        },
        {"type": "message_stop"},
    ]
    return b"".join(b"data: " + json.dumps(f).encode() + b"\n\n" for f in frames)

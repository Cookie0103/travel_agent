"""只有完整最终 usage 可以结算；伪完整流不能释放预占费用。"""

import json

import pytest

from backend.providers.claude_agent.request import validate_request
from backend.providers.claude_agent.response import summarize
from backend.providers.probe.settings import ProbeError
from tests.test_sdk_guard import request_body, response_body


@pytest.mark.parametrize(
    "mutation",
    [
        "no_delta",
        "duplicate_start",
        "duplicate_stop",
        "missing_output",
        "trailing",
        "output_decrease",
        "after_final",
        "open_block",
    ],
)
def test_incomplete_or_duplicate_sse_never_settles(mutation: str) -> None:
    frames = [
        json.loads(line[5:])
        for line in response_body().decode().splitlines()
        if line.startswith("data:")
    ]
    if mutation == "no_delta":
        frames.pop(1)
    elif mutation == "duplicate_start":
        frames.insert(1, frames[0])
    elif mutation == "duplicate_stop":
        frames.append(frames[-1])
    elif mutation == "missing_output":
        frames[1]["usage"] = {}
    elif mutation == "output_decrease":
        frames[0]["message"]["usage"]["output_tokens"] = 500
    elif mutation == "after_final":
        frames.insert(-1, {"type": "content_block_delta", "index": 0})
    elif mutation == "open_block":
        frames.insert(1, {"type": "content_block_start", "index": 0})
    else:
        frames.append({"type": "content_block_delta"})
    content = b"".join(b"data: " + json.dumps(f).encode() + b"\n\n" for f in frames)
    with pytest.raises(ProbeError):
        summarize(content, validate_request(request_body(), "deepseek-flash"), "deepseek-flash")

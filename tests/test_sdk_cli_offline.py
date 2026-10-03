"""真实 SDK/CLI 与本地脚本化 API 的往返，不访问付费模型或读取 .env。"""

import json
import os
import shutil
from decimal import Decimal
from functools import partial
from pathlib import Path

import pytest

from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import find_cli, worker_environment
from backend.providers.claude_agent.guard import Guard, serve
from backend.providers.claude_agent.process import invoke_worker
from backend.providers.claude_agent.request import TOOL_NAME
from backend.providers.probe.settings import Settings


def scripted_response(
    body: bytes,
    *,
    invalid_argument: bool = False,
    tool_calls: tuple[tuple[str, dict[str, object]], ...] | None = None,
) -> tuple[int, bytes]:
    request = json.loads(body)
    results = [
        part["content"]
        for message in request["messages"]
        if isinstance(message.get("content"), list)
        for part in message["content"]
        if isinstance(part, dict) and part.get("type") == "tool_result"
    ]
    has_result = bool(results)
    frames: list[dict[str, object]] = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_offline",
                "type": "message",
                "role": "assistant",
                "model": "deepseek-flash",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 0},
            },
        }
    ]
    calls = tool_calls or ((TOOL_NAME, {"text": "wrong" if invalid_argument else "kyoto-sdk-ok"}),)
    blocks: list[tuple[dict[str, object], dict[str, object]]]
    if has_result:
        blocks = [
            ({"type": "text", "text": ""}, {"type": "text_delta", "text": json.dumps(results)})
        ]
    else:
        blocks = [
            (
                {"type": "tool_use", "id": f"tool_{i}", "name": name, "input": {}},
                {"type": "input_json_delta", "partial_json": json.dumps(arguments)},
            )
            for i, (name, arguments) in enumerate(calls)
        ]
    if invalid_argument and has_result:
        assert any(
            part.get("is_error") is True
            for message in request["messages"]
            if isinstance(message.get("content"), list)
            for part in message["content"]
            if part.get("type") == "tool_result"
        ), "SDK must mark schema validation failure in the tool result"
    for index, (block, delta) in enumerate(blocks):
        frames.extend(
            [
                {"type": "content_block_start", "index": index, "content_block": block},
                {"type": "content_block_delta", "index": index, "delta": delta},
                {"type": "content_block_stop", "index": index},
            ]
        )
    frames.extend(
        [
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": "end_turn" if has_result else "tool_use",
                    "stop_sequence": None,
                },
                "usage": {"output_tokens": 20},
            },
            {"type": "message_stop"},
        ]
    )
    return 200, b"".join(
        ("event: " + str(f["type"]) + "\ndata: " + json.dumps(f) + "\n\n").encode() for f in frames
    )


@pytest.mark.skipif(not shutil.which("claude"), reason="实际 CLI 未安装；替身不能冒充 CLI 验证")
@pytest.mark.parametrize("invalid_argument", [False, True])
def test_real_sdk_and_cli_call_only_synthetic_tool_offline(
    tmp_path: Path, invalid_argument: bool
) -> None:
    """R01/R02：真实 MCP 握手和工具往返，模型输出是本地脚本，不是模型质量证据。"""
    root = Path(__file__).resolve().parents[1]
    budget = Budget(tmp_path / "ledger", tmp_path / "old", Decimal(5))
    guard = Guard(
        Settings("never-forwarded", "deepseek-flash", Decimal(5), Decimal(0)),
        budget,
        partial(scripted_response, invalid_argument=invalid_argument),
    )
    with serve(guard) as endpoint:
        env = worker_environment(
            os.environ, tmp_path / "worker", root, endpoint, guard.token, "deepseek-flash"
        )
        report = invoke_worker(find_cli(os.environ), tmp_path / "worker", env)
    assert report["status"] == ("error" if invalid_argument else "success"), (
        report,
        guard.failures,
    )
    if invalid_argument:
        assert report["code"] == "tool_roundtrip_missing", report
    assert guard.attempts == 2
    assert guard.failures == []

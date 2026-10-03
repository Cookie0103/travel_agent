"""真实 SDK/CLI 与本地脚本化 API 的往返，不访问付费模型或读取 .env。"""

import json
import os
import shutil
from decimal import Decimal
from functools import partial
from pathlib import Path

import pytest

from backend.providers.probe.settings import Settings
from backend.providers.sdk_probe.budget import Budget
from backend.providers.sdk_probe.environment import find_cli, worker_environment
from backend.providers.sdk_probe.flow import invoke_worker
from backend.providers.sdk_probe.guard import Guard, serve
from backend.providers.sdk_probe.request import TOOL_NAME


def scripted_response(body: bytes, *, invalid_argument: bool = False) -> tuple[int, bytes]:
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
    block: dict[str, object]
    if has_result:
        block = {"type": "text", "text": ""}
        delta = {"type": "text_delta", "text": json.dumps(results[-1])}
    else:
        block = {"type": "tool_use", "id": "tool_offline", "name": TOOL_NAME, "input": {}}
        delta = {
            "type": "input_json_delta",
            "partial_json": json.dumps({"text": "wrong" if invalid_argument else "kyoto-sdk-ok"}),
        }
    if invalid_argument and has_result:
        assert any(
            part.get("is_error") is True
            for message in request["messages"]
            if isinstance(message.get("content"), list)
            for part in message["content"]
            if part.get("type") == "tool_result"
        ), "SDK must mark schema validation failure in the tool result"
    frames.extend(
        [
            {"type": "content_block_start", "index": 0, "content_block": block},
            {"type": "content_block_delta", "index": 0, "delta": delta},
            {"type": "content_block_stop", "index": 0},
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
        assert report["code"] == "tool_roundtrip_missing"
    assert guard.attempts == 2
    assert guard.failures == []

"""真实 SDK/CLI 与本地脚本化 API 的往返，不访问付费模型或读取 .env。"""

import json
import os
import shutil
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from backend.limits import Settings
from backend.mcp.bridge import sdk_tool_name
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import find_cli, worker_environment
from backend.providers.claude_agent.guard import Guard, serve
from backend.providers.claude_agent.process import run_process
from backend.providers.claude_agent.request import TOOL_NAME
from backend.tools.search import DEFINITIONS


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
                # 旧场景用空messages作为脚本阶段控制，实际出站请求仍经Guard严格核对模型。
                "model": request.get("model", "deepseek-flash"),
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


TERMINAL_PROGRAM = """
import asyncio,json,sys
from pathlib import Path
from uuid import uuid4
from claude_agent_sdk import ClaudeSDKClient,ResultMessage
from backend.domain.execution import RunContext,RuntimeIdentity
from backend.providers.claude_agent.runtime import ClaudeRuntime,RuntimeConfig,outcome_from_result
from backend.tools.search import DEFINITIONS,SearchExecutor
async def run():
    context=RunContext(uuid4())
    config=RuntimeConfig(RuntimeIdentity('deepseek','deepseek-flash','0.2.163','2.1.114'),
                        Path(sys.argv[1]),Path.cwd(),'Use only travel tools.',max_turns=2)
    runtime=ClaudeRuntime(config,DEFINITIONS[:1],SearchExecutor())
    async with ClaudeSDKClient(options=runtime.options(context,None,lambda e:None)) as client:
        await client.query('Search Kyoto')
        async for message in client.receive_response():
            if isinstance(message,ResultMessage):
                outcome=outcome_from_result(message)
                print(json.dumps({'subtype':message.subtype,'stop_reason':message.stop_reason,
                    'terminal_reason':message.terminal_reason,'is_error':message.is_error,
                    'outcome_code':outcome.code,'outcome_reason':outcome.reason}))
asyncio.run(run())
"""


@pytest.mark.skipif(not shutil.which("claude"), reason="需要真实CLI，本机响应不调用模型")
@pytest.mark.parametrize("flavor", ["tool_loop", "truncated_text"])
def test_real_sdk_terminal_limit_and_output_continuations_remain_failure(
    tmp_path: Path, flavor: str
) -> None:
    """R01/R17：实际Result同时有tool_use/max_turns；截断内续请求也要全部计数。"""
    count = 0

    def forward(body: bytes) -> tuple[int, bytes]:
        nonlocal count
        count += 1
        request = json.loads(body)
        request["messages"] = (
            []
            if flavor == "tool_loop"
            else [{"content": [{"type": "tool_result", "content": "synthetic"}]}]
        )
        status, content = scripted_response(
            json.dumps(request).encode(),
            tool_calls=(
                (sdk_tool_name(DEFINITIONS[0].name), {"city": "京都", "query": "寺庙", "limit": 1}),
            ),
        )
        content = content.replace(b'"tool_0"', f'"terminal_{count}"'.encode())
        if flavor == "truncated_text":
            content = content.replace(b'"stop_reason": "end_turn"', b'"stop_reason": "max_tokens"')
        return status, content

    guard = Guard(
        Settings("synthetic-local-only", "deepseek-flash", Decimal(5), Decimal(0)),
        Budget(tmp_path / "ledger", tmp_path / "old", Decimal(5)),
        forward,
        max_attempts=12,
        allowed_tools=frozenset({sdk_tool_name(DEFINITIONS[0].name)}),
    )
    with serve(guard) as endpoint:
        directory = tmp_path / "worker"
        env = worker_environment(
            os.environ,
            directory,
            Path(__file__).resolve().parents[1],
            endpoint,
            guard.token,
            "deepseek-flash",
        )
        result = run_process(
            [sys.executable, "-c", TERMINAL_PROGRAM, str(find_cli(os.environ))],
            directory,
            env,
            timeout=60,
        )
    assert result.returncode == 0
    metadata = json.loads(result.stdout.strip())
    assert metadata["is_error"] is True and not guard.failures
    if flavor == "tool_loop":
        assert metadata["subtype"] == "error_max_turns" and metadata["stop_reason"] == "tool_use"
        assert metadata["terminal_reason"] == "max_turns" and guard.attempts == 2
        assert metadata["outcome_code"] == "blocked" and metadata["outcome_reason"] == "max_turns"
    else:
        assert metadata["outcome_code"] == "provider_error"
        assert guard.attempts == 4 and len(guard.observations) == 4
        assert all(row["stop_reason"] == "max_tokens" for row in guard.observations)

"""隔离子进程内调用 SDK；仅回传白名单摘要，不外泄 SDK 原始错误。"""

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)

from backend.providers.sdk_probe.request import TOOL_NAME

PROMPT = "Call the echo tool with text='kyoto-sdk-ok', then reply with that exact tool result."
DIAGNOSTICS: set[str] = set()


async def run_worker(cli: Path) -> dict[str, object]:
    calls: list[str] = []
    expected = "kyoto-sdk-ok:" + secrets.token_hex(16)
    options = make_options(cli, calls, expected)
    messages: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(PROMPT)
        async for message in client.receive_response():
            messages.append(type(message).__name__)
            if isinstance(message, AssistantMessage):
                if any(
                    isinstance(b, ToolUseBlock) and b.name != TOOL_NAME for b in message.content
                ):
                    await client.interrupt()
                    return {"status": "error", "code": "unknown_tool"}
            if isinstance(message, ResultMessage):
                return result_summary(message, calls, messages, expected)
    return {"status": "error", "code": "incomplete_stream"}


def make_options(cli: Path, calls: list[str], expected: str) -> ClaudeAgentOptions:

    @tool(
        "echo",
        "Return text plus a fresh server challenge; synthetic read-only integration test.",
        {
            "type": "object",
            "properties": {"text": {"type": "string", "const": "kyoto-sdk-ok"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )
    async def echo(args: dict[str, object]) -> dict[str, object]:
        # SDK 已根据这份 schema 校验参数，这里只产生探针业务结果。
        calls.append("echo")
        return {"content": [{"type": "text", "text": expected}]}

    return ClaudeAgentOptions(
        model=os.environ["ANTHROPIC_MODEL"],
        cli_path=cli,
        cwd=Path.cwd(),
        system_prompt="Use only the provided read-only tool; return its result in one sentence.",
        tools=[],
        allowed_tools=[TOOL_NAME],
        strict_mcp_config=True,
        mcp_servers={"probe": create_sdk_mcp_server("probe", tools=[echo])},
        setting_sources=[],
        skills=[],
        plugins=[],
        permission_mode="default",
        max_turns=3,
        thinking={"type": "disabled"},
        stderr=collect_diagnostics,
    )


def result_summary(
    message: ResultMessage, calls: list[str], events: list[str], expected: str
) -> dict[str, object]:
    reason = message.terminal_reason
    if message.is_error or message.subtype != "success" or reason not in {None, "completed"}:
        return {"status": "error", "code": "runtime_error", "terminal_reason": reason}
    if calls != ["echo"] or not message.result or expected not in message.result:
        return {"status": "error", "code": "tool_roundtrip_missing"}
    return {
        "status": "success",
        "tool_calls": calls,
        "sdk_events": events,
        "session_id": message.session_id,
        "terminal_reason": reason,
    }


def main() -> None:
    try:
        result = asyncio.run(timed_worker(Path(sys.argv[1])))
    except Exception as error:
        # SDK 异常可包含原始响应与路径；只输出类名，不转发异常正文。
        result = {"status": "error", "code": "sdk_failure", "error_type": type(error).__name__}
        result["diagnostics"] = sorted(DIAGNOSTICS)
    print(json.dumps(result))


async def timed_worker(cli: Path) -> dict[str, object]:
    """先让 SDK 在取消上下文中正常释放 CLI，父进程期限是最后保护。"""
    try:
        async with asyncio.timeout(90):
            return await run_worker(cli)
    except TimeoutError:
        return {"status": "error", "code": "timeout"}


def collect_diagnostics(line: str) -> None:
    """仅提取固定机器错误码/类别；不向应用返回原始 stderr。"""
    DIAGNOSTICS.update(
        code
        for code in ("EACCES", "ENOENT", "EPERM", "ENAMETOOLONG", "ENOSPC", "EINVAL")
        if code in line
    )
    lowered = line.lower()
    for word in (
        "permission",
        "not found",
        "git-bash",
        "unknown option",
        "mcp",
        "too long",
        "access",
    ):
        if word in lowered:
            DIAGNOSTICS.add(word)


if __name__ == "__main__":
    main()

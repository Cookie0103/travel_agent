"""R01/R02：脚本化 SDK 消息验证薄适配，不手工回填模型工具结果。"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import TracebackType
from uuid import uuid4

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    Message,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from backend.domain.execution import RunContext, RuntimeEvent, RuntimeIdentity
from backend.providers.claude_agent.runtime import (
    ClaudeRuntime,
    RuntimeConfig,
    literal_prompt_supported,
)
from backend.tools.contracts import ToolResult


class Executor:
    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        raise AssertionError("脚本消息测试不能隐式执行业务工具")


class ScriptedClient:
    def __init__(self, messages: list[Message], *, hang: bool = False) -> None:
        self.messages, self.hang = messages, hang
        self.closed = self.interrupted = False
        self.queried = asyncio.Event()
        self.options: ClaudeAgentOptions | None = None

    async def __aenter__(self) -> "ScriptedClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.closed = True

    async def query(self, prompt: str) -> None:
        self.queried.set()

    async def receive_response(self) -> AsyncIterator[Message]:
        if self.hang:
            await asyncio.Event().wait()
        for message in self.messages:
            yield message

    async def interrupt(self) -> None:
        self.interrupted = True


def runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: ScriptedClient, timeout: float = 1
) -> ClaudeRuntime:
    def factory(*, options: ClaudeAgentOptions) -> ScriptedClient:
        client.options = options
        return client

    monkeypatch.setattr("backend.providers.claude_agent.runtime.ClaudeSDKClient", factory)
    config = RuntimeConfig(
        RuntimeIdentity("deepseek", "deepseek-flash", "test", "2.1.114"),
        tmp_path / "claude.exe",
        tmp_path,
        "Only travel tools.",
        timeout_seconds=timeout,
    )
    return ClaudeRuntime(config, (), Executor())


@pytest.mark.asyncio
async def test_complete_result_translates_and_closes_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = ScriptedClient(
        [
            AssistantMessage([TextBlock("京都")], "deepseek-flash"),
            ResultMessage("success", 1, 1, False, 1, "sdk-session", result="京都"),
        ]
    )
    adapter = runtime(tmp_path, monkeypatch, client)
    events: list[RuntimeEvent] = []
    outcome = await adapter.execute(
        RunContext(uuid4()), "问", "known-sdk", events.append, asyncio.Event()
    )
    assert outcome.text == "京都" and outcome.code is None and client.closed
    assert [e.text for e in events] == ["京都"]
    assert client.options and client.options.resume == "known-sdk"
    assert client.options.tools == [] and client.options.setting_sources == []
    assert client.options.permission_mode == "dontAsk" and client.options.verbatim_prompts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason,code",
    [
        ("max_turns", "blocked"),
        ("aborted_streaming", "cancelled"),
        ("future_reason", "provider_error"),
    ],
)
async def test_noncomplete_terminal_reason_is_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str, code: str
) -> None:
    client = ScriptedClient(
        [ResultMessage("success", 1, 1, False, 1, "sdk", result="partial", terminal_reason=reason)]
    )
    outcome = await runtime(tmp_path, monkeypatch, client).execute(
        RunContext(uuid4()), "问", None, lambda e: None, asyncio.Event()
    )
    assert outcome.code == code and outcome.sdk_session_id is None and client.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown_tool", [False, True])
async def test_half_stream_and_unknown_tool_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unknown_tool: bool
) -> None:
    messages: list[Message] = [AssistantMessage([TextBlock("partial")], "deepseek-flash")]
    if unknown_tool:
        messages = [
            AssistantMessage([ToolUseBlock("one", "Bash", {"command": "no"})], "deepseek-flash")
        ]
    client = ScriptedClient(messages)
    outcome = await runtime(tmp_path, monkeypatch, client).execute(
        RunContext(uuid4()), "问", None, lambda e: None, asyncio.Event()
    )
    assert outcome.code == "provider_error" and client.closed
    assert client.interrupted == unknown_tool


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [True, False])
async def test_timeout_and_cancel_close_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timeout: bool
) -> None:
    client = ScriptedClient([], hang=True)
    adapter = runtime(tmp_path, monkeypatch, client, timeout=0.02 if timeout else 2)
    cancelled = asyncio.Event()
    task = asyncio.create_task(
        adapter.execute(RunContext(uuid4()), "问", None, lambda e: None, cancelled)
    )
    await client.queried.wait()
    if not timeout:
        cancelled.set()
    result = await asyncio.wait_for(task, 1)
    assert result.code == ("timeout" if timeout else "cancelled") and client.closed


@pytest.mark.parametrize("prompt", ["@/private.txt", "/help", "京都\n /compact"])
def test_older_cli_cannot_expand_user_input(prompt: str) -> None:
    assert not literal_prompt_supported(prompt, "2.1.114")
    assert literal_prompt_supported(prompt, "2.1.248")

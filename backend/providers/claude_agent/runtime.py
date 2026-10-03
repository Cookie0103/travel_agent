"""在隔离工作进程内调用 SDK；SDK 负责循环，本模块负责生命周期和事件转换。"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeIdentity, RuntimeOutcome
from backend.mcp.bridge import build_server, sdk_tool_name
from backend.tools.contracts import ToolDefinition, ToolExecutor
from backend.tools.workflow import OrderedTools, WorkflowName, workflow_guidance


@dataclass(frozen=True)
class RuntimeConfig:
    identity: RuntimeIdentity
    cli: Path
    directory: Path
    system_prompt: str
    max_turns: int = 6
    timeout_seconds: float = 90
    workflow: WorkflowName | None = None


class ClaudeRuntime:
    """仅在 worker_environment 产生的隔离进程里实例化；不持有真实模型密钥。"""

    def __init__(
        self,
        config: RuntimeConfig,
        definitions: tuple[ToolDefinition, ...],
        executor: ToolExecutor,
    ) -> None:
        self.config, self.definitions, self.executor = config, definitions, executor
        if config.workflow:
            self.executor = OrderedTools(executor, config.workflow)
        self.identity = config.identity

    async def execute(
        self,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        if not literal_prompt_supported(prompt, self.identity.cli_version):
            return RuntimeOutcome(code="blocked", reason="cli_prompt_expansion")
        if cancelled.is_set():
            return RuntimeOutcome(code="cancelled", reason="cancelled")
        task = asyncio.create_task(self._execute(context, prompt, sdk_session_id, emit))
        cancellation = asyncio.create_task(cancelled.wait())
        try:
            done, _ = await asyncio.wait((task, cancellation), return_when=asyncio.FIRST_COMPLETED)
            if task not in done:
                task.cancel()
            return await task
        except asyncio.CancelledError:
            return RuntimeOutcome(code="cancelled", reason="cancelled")
        finally:
            cancellation.cancel()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, cancellation, return_exceptions=True)

    async def _execute(
        self,
        context: RunContext,
        prompt: str,
        sdk_id: str | None,
        emit: EventSink,
    ) -> RuntimeOutcome:
        options = self.options(context, sdk_id, emit)
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                async with ClaudeSDKClient(options=options) as client:
                    await client.query(prompt)
                    return await self._collect(client, context, emit)
        except TimeoutError:
            return RuntimeOutcome(code="timeout", reason="runtime_timeout")
        except asyncio.CancelledError:
            raise
        except Exception:
            # SDK 异常可能含密钥、原始上下文和路径，不进入应用事件。
            return RuntimeOutcome(code="provider_error", reason="sdk_failure")
        return RuntimeOutcome(code="provider_error", reason="incomplete_stream")

    async def _collect(
        self, client: ClaudeSDKClient, context: RunContext, emit: EventSink
    ) -> RuntimeOutcome:
        allowed = {sdk_tool_name(d.name) for d in self.definitions}
        async for message in client.receive_response():
            if isinstance(message, SystemMessage) and message.subtype == "compact_boundary":
                emit(RuntimeEvent(context, "context_compacted"))
            if isinstance(message, AssistantMessage):
                if (
                    message.error
                    or message.model != self.identity.model
                    or any(
                        isinstance(b, ToolUseBlock) and b.name not in allowed
                        for b in message.content
                    )
                ):
                    await client.interrupt()
                    return RuntimeOutcome(code="provider_error", reason="invalid_assistant_message")
                for block in message.content:
                    if isinstance(block, TextBlock):
                        emit(RuntimeEvent(context, "text", text=block.text))
            if isinstance(message, ResultMessage):
                return outcome_from_result(message)
        return RuntimeOutcome(code="provider_error", reason="incomplete_stream")

    def options(
        self, context: RunContext, sdk_id: str | None, emit: EventSink
    ) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            cli_path=self.config.cli,
            cwd=self.config.directory,
            model=self.identity.model,
            system_prompt=self.config.system_prompt
            + (workflow_guidance(self.config.workflow) if self.config.workflow else ""),
            tools=[],
            allowed_tools=[sdk_tool_name(d.name) for d in self.definitions],
            mcp_servers={"travel": build_server(self.definitions, self.executor, context, emit)},
            strict_mcp_config=True,
            setting_sources=[],
            skills=[],
            plugins=[],
            permission_mode="dontAsk",
            max_turns=self.config.max_turns,
            thinking={"type": "disabled"},
            verbatim_prompts=True,
            resume=sdk_id,
        )


def outcome_from_result(message: ResultMessage) -> RuntimeOutcome:
    reason = message.terminal_reason
    if message.stop_reason not in {None, "end_turn", "stop_sequence"}:
        return RuntimeOutcome(code="provider_error", reason="incomplete_output")
    if reason in {"aborted_streaming", "aborted_tools"}:
        return RuntimeOutcome(code="cancelled", reason=reason)
    if reason == "max_turns" or message.subtype == "error_max_turns":
        return RuntimeOutcome(code="blocked", reason="max_turns")
    if message.api_error_status == 429:
        return RuntimeOutcome(code="rate_limited", reason="provider_rate_limit")
    if message.is_error or message.subtype != "success" or reason not in {None, "completed"}:
        return RuntimeOutcome(code="provider_error", reason="sdk_result_error")
    if not message.session_id or message.result is None:
        return RuntimeOutcome(code="provider_error", reason="incomplete_result")
    return RuntimeOutcome(message.result, message.session_id)


def literal_prompt_supported(prompt: str, cli_version: str) -> bool:
    """旧 CLI 忽略 verbatim_prompts；有展开语法则拒绝，不能靠系统提示词阻止读文件。"""
    try:
        version = tuple(int(part) for part in cli_version.split(".")[:3])
    except ValueError:
        version = ()
    return version >= (2, 1, 248) or (
        "@" not in prompt and not any(line.lstrip().startswith("/") for line in prompt.splitlines())
    )

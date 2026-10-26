"""在隔离工作进程内调用 SDK；SDK 负责循环，本模块负责生命周期和事件转换。"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)
from claude_agent_sdk.types import HookContext, HookEvent, HookInput, HookJSONOutput

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeIdentity, RuntimeOutcome
from backend.mcp.bridge import build_server, sdk_tool_name
from backend.tools.contracts import ToolDefinition, ToolExecutor
from backend.tools.workflow import OrderedTools, WorkflowName, workflow_guidance
from backend.trace_log import trace

# 行程需要连续约6-10次工具调用（路线、校验、暂存、展示）；一次提醒不够，
# 但必须有界，否则模型空转会无限消耗调用额度。
MAX_STOP_CORRECTIONS = 3
# 已离线实测“关闭自动压缩”开关的 (SDK, CLI) 组合；新增必须先做独立核验（安全边界，勿放宽）。
VERIFIED_COMPACTION_CONTROL = (
    ("0.2.163", "2.1.114"),
    ("0.2.163", "2.1.294"),
    ("0.2.163", "2.1.295"),
)


def unverified_compaction_message(sdk_version: str, cli_version: str) -> str:
    verified = ", ".join(f"SDK {sdk}/CLI {cli}" for sdk, cli in VERIFIED_COMPACTION_CONTROL)
    return (
        f"当前 SDK {sdk_version or '?'}/CLI {cli_version or '?'} 不在已验证列表 [{verified}]；"
        "请安装 npm install --global @anthropic-ai/claude-code@2.1.295，"
        "或运行 uv run python scripts/dev.py doctor 检查本机环境；"
        "要把新版本加入列表须先独立离线核验关闭自动压缩的行为。"
    )


@dataclass(frozen=True)
class RuntimeConfig:
    identity: RuntimeIdentity
    cli: Path
    directory: Path
    system_prompt: str
    # 逐轮业务状态前置块：拼在用户消息前，保持system跨轮不变以复用缓存前缀。
    turn_prefix: str = ""
    max_turns: int | None = 6
    timeout_seconds: float = 90
    workflow: WorkflowName | None = None
    disable_auto_compaction: bool = False
    persist_session: bool = True
    stop_check: Callable[[RunContext, int], Awaitable[str | None]] | None = None
    # 压缩会把本轮前置块摘要掉；读取最新业务状态，压缩后补回一次。
    refresh_state: Callable[[RunContext], Awaitable[str]] | None = None


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
        self.stop_corrections = 0
        self.stop_failure: str | None = None
        # 压缩后尚未补回业务状态；每次压缩只补一次，有界。
        self.state_lost = False

    async def execute(
        self,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        prompt = self.config.turn_prefix + prompt
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
        if (
            self.config.disable_auto_compaction
            and (self.identity.sdk_version, self.identity.cli_version)
            not in VERIFIED_COMPACTION_CONTROL
        ):
            # 带工具get_context_usage会请求计数API；不放开费用守卫来逐轮探测。
            # 仅使用已实测的锁定版本/官方开关，未知版本须先独立离线核验。
            return RuntimeOutcome(
                text=unverified_compaction_message(
                    self.identity.sdk_version, self.identity.cli_version
                ),
                code="blocked",
                reason="auto_compaction_capability",
            )
        options = self.options(context, sdk_id, emit)
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                async with ClaudeSDKClient(options=options) as client:
                    await client.query(prompt)
                    trace("sdk_turn_start", context.run_id, turn=0, max_turns=self.config.max_turns)
                    return await self._collect(client, context, emit)
        except TimeoutError:
            trace(
                "timeout_fired",
                context.run_id,
                layer="worker_sdk",
                limit_s=self.config.timeout_seconds,
            )
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
        turn, mark = 0, time.monotonic()
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                # 一次助手消息=模型一轮响应结束；elapsed为距上一边界（含工具执行+模型等待）。
                trace(
                    "sdk_turn_end",
                    context.run_id,
                    turn=turn,
                    elapsed_ms=round((time.monotonic() - mark) * 1000),
                    stop_reason=message.stop_reason,
                    blocks=len(message.content),
                    tools=[b.name for b in message.content if isinstance(b, ToolUseBlock)],
                    output_tokens=(message.usage or {}).get("output_tokens"),
                )
                turn, mark = turn + 1, time.monotonic()
            if isinstance(message, ResultMessage):
                trace(
                    "sdk_result",
                    context.run_id,
                    subtype=message.subtype,
                    terminal_reason=message.terminal_reason,
                    stop_reason=message.stop_reason,
                    num_turns=message.num_turns,
                    duration_ms=message.duration_ms,
                    duration_api_ms=message.duration_api_ms,
                    api_error_status=message.api_error_status,
                )
            if isinstance(message, SystemMessage) and message.subtype == "compact_boundary":
                trace("context_compacted", context.run_id, turn=turn)
                emit(RuntimeEvent(context, "context_compacted"))
                if self.config.disable_auto_compaction:
                    await client.interrupt()
                    return RuntimeOutcome(code="blocked", reason="unexpected_auto_compaction")
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
                outcome = outcome_from_result(message)
                business_stop = (
                    message.terminal_reason == "stop_hook_prevented"
                    and message.subtype == "success"
                    and not message.is_error
                    and message.api_error_status is None
                    and message.stop_reason in {None, "end_turn", "stop_sequence"}
                    and self.stop_failure
                    in {"conversation_incomplete", "conversation_state_unavailable"}
                )
                if self.stop_failure and (outcome.code is None or business_stop):
                    return RuntimeOutcome(
                        text="本轮未完成查询或草稿生成，请稍后继续。",
                        code="unavailable"
                        if self.stop_failure == "conversation_state_unavailable"
                        else "blocked",
                        reason=self.stop_failure,
                    )
                return outcome
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
            hooks=self.hooks(context),
            max_turns=self.config.max_turns,
            thinking={"type": "disabled"},
            verbatim_prompts=True,
            resume=sdk_id,
            env={"DISABLE_AUTO_COMPACT": "1"} if self.config.disable_auto_compaction else {},
            extra_args={} if self.config.persist_session else {"no-session-persistence": None},
        )

    def hooks(self, context: RunContext) -> dict[HookEvent, list[HookMatcher]] | None:
        hooks: dict[HookEvent, list[HookMatcher]] = {}
        if self.config.stop_check or self.config.refresh_state:
            hooks["Stop"] = [HookMatcher(hooks=[self.stop_hook(context)], timeout=5)]
        if self.config.refresh_state:
            hooks["PreCompact"] = [HookMatcher(hooks=[self.compact_hook()], timeout=5)]
            hooks["PostToolUse"] = [HookMatcher(hooks=[self.restore_hook(context)], timeout=5)]
        return hooks or None

    def compact_hook(
        self,
    ) -> Callable[[HookInput, str | None, HookContext], Awaitable[HookJSONOutput]]:
        async def mark(
            data: HookInput, tool_id: str | None, hook_context: HookContext
        ) -> HookJSONOutput:
            if data["hook_event_name"] == "PreCompact":
                self.state_lost = True
            return {}

        return mark

    def restore_hook(
        self, context: RunContext
    ) -> Callable[[HookInput, str | None, HookContext], Awaitable[HookJSONOutput]]:
        async def restore(
            data: HookInput, tool_id: str | None, hook_context: HookContext
        ) -> HookJSONOutput:
            if data["hook_event_name"] != "PostToolUse" or not self.state_lost:
                return {}
            state = await self.restored_state(context)
            if state is None:
                return {}  # 读取失败留给Stop钩子再试，仍失败则不冒称完成
            return {
                "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": state}
            }

        return restore

    async def restored_state(self, context: RunContext) -> str | None:
        assert self.config.refresh_state is not None
        try:
            state = await self.config.refresh_state(context)
        except Exception:
            return None
        self.state_lost = False
        trace("state_restored", context.run_id)
        return state

    def stop_hook(
        self, context: RunContext
    ) -> Callable[[HookInput, str | None, HookContext], Awaitable[HookJSONOutput]]:
        async def check(
            data: HookInput, tool_id: str | None, hook_context: HookContext
        ) -> HookJSONOutput:
            if data["hook_event_name"] != "Stop":
                return {}
            if self.state_lost and self.config.refresh_state:
                # 压缩后没有工具调用可携带状态：拦一次结束，补回状态再答，不计入续跑提醒次数。
                state = await self.restored_state(context)
                if state is None:
                    self.stop_failure = "conversation_state_unavailable"
                    return {"continue_": False, "stopReason": "业务状态暂不可读取，请稍后重试"}
                return {
                    "decision": "block",
                    "reason": "上下文刚被压缩，请按以下最新服务端状态核对后再回复用户：\n" + state,
                }
            if self.config.stop_check is None:
                return {}
            try:
                reason = await self.config.stop_check(context, self.stop_corrections + 1)
            except Exception:
                # 不把数据库/用户/供应商异常正文返回给SDK；无法读取状态时不能冒称任务完成。
                self.stop_failure = "conversation_state_unavailable"
                return {"continue_": False, "stopReason": "业务状态暂不可读取，请稍后重试"}
            if reason is None:
                return {}
            # 循环上界只看自己的计数；SDK的stop_hook_active只表示此前已触发过Stop钩子。
            if self.stop_corrections >= MAX_STOP_CORRECTIONS:
                self.stop_failure = "conversation_incomplete"
                return {"continue_": False, "stopReason": "本轮未完成已授权的旅行任务"}
            self.stop_corrections += 1
            return {"decision": "block", "reason": reason}

        return check


def outcome_from_result(message: ResultMessage) -> RuntimeOutcome:
    reason = message.terminal_reason
    # SDK轮数终止仍可能保留最后一次tool_use；停止原因不能掩盖已知执行边界。
    if reason in {"aborted_streaming", "aborted_tools"}:
        return RuntimeOutcome(code="cancelled", reason=reason)
    if reason == "max_turns" or message.subtype == "error_max_turns":
        return RuntimeOutcome(code="blocked", reason="max_turns")
    if message.stop_reason not in {None, "end_turn", "stop_sequence"}:
        return RuntimeOutcome(code="provider_error", reason="incomplete_output")
    if message.api_error_status == 429:
        return RuntimeOutcome(code="rate_limited", reason="provider_rate_limit")
    if message.api_error_status is not None:
        return RuntimeOutcome(code="provider_error", reason="provider_api_error")
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

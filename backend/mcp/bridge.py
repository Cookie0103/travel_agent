"""把共享工具契约接到 SDK 进程内 MCP；模型参数不能覆盖服务端身份。"""

import json

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext
from backend.tools.contracts import (
    WRITE_KINDS,
    ToolDefinition,
    ToolExecutor,
    ToolResult,
    committed_confirmation,
)
from backend.tools.execution import execute_observed
from backend.tools.fencing import fence_payload


class Recorder:
    """记录执行器已返回的首个结果，供展示/序列化失败时判断写入是否已发生。"""

    def __init__(self, executor: ToolExecutor, finished: list[ToolResult]) -> None:
        self.executor, self.finished = executor, finished

    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        result = await self.executor.execute(context, name, arguments)
        self.finished.append(result)
        return result


def sdk_tool_name(name: str) -> str:
    return f"mcp__travel__{name}"


def build_server(
    definitions: tuple[ToolDefinition, ...],
    executor: ToolExecutor,
    context: RunContext,
    emit: EventSink,
) -> McpSdkServerConfig:
    if len({d.name for d in definitions}) != len(definitions):
        raise ValueError("工具名称不能重复")
    return create_sdk_mcp_server(
        "travel", tools=[_build_tool(d, executor, context, emit) for d in definitions]
    )


def _build_tool(
    definition: ToolDefinition,
    executor: ToolExecutor,
    context: RunContext,
    emit: EventSink,
) -> SdkMcpTool[dict[str, object]]:
    @tool(definition.name, definition.description, definition.schema)
    async def handler(arguments: dict[str, object]) -> dict[str, object]:
        finished: list[ToolResult] = []
        try:
            result = await execute_observed(
                Recorder(executor, finished),
                context,
                definition.name,
                arguments,
                emit,
                definition=definition,
            )
            # 唯一围栏点：仅实时模型路径；评测/API/离线演示读取未围栏的ToolResult。
            payload = json.dumps(
                fence_payload(result.payload(), definition.name), ensure_ascii=False
            )
        except Exception:
            # 事件接收器/序列化也可能抛异常；不能交给 SDK 的 str(error) 透传。
            if finished and definition.kind in WRITE_KINDS:
                # 写入已提交：报成失败会让模型重试出重复写入，只回最小确认。
                result = committed_confirmation(finished[0])
            else:
                result = ToolResult({}, code="unavailable")
            payload = json.dumps(result.payload(), ensure_ascii=False, default=str)
        return {
            "content": [{"type": "text", "text": payload}],
            "is_error": result.code is not None,
        }

    return handler

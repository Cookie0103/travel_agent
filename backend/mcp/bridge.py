"""把共享工具契约接到 SDK 进程内 MCP；模型参数不能覆盖服务端身份。"""

import json

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext
from backend.tools.contracts import ToolDefinition, ToolExecutor, ToolResult
from backend.tools.execution import execute_observed


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
        try:
            result = await execute_observed(
                executor, context, definition.name, arguments, emit, definition=definition
            )
            payload = json.dumps(result.payload(), ensure_ascii=False)
        except Exception:
            # 事件接收器/序列化也可能抛异常；不能交给 SDK 的 str(error) 透传。
            result = ToolResult({}, code="unavailable")
            payload = json.dumps(result.payload(), ensure_ascii=False)
        return {
            "content": [{"type": "text", "text": payload}],
            "is_error": result.code is not None,
        }

    return handler

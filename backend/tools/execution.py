"""共用的工具事件转换；SDK和离线演示走同一业务入口，不负责选择或调度工具。"""

from uuid import uuid4

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeEvent
from backend.tools.contracts import ToolExecutor, ToolResult


async def execute_observed(
    executor: ToolExecutor,
    context: RunContext,
    name: str,
    arguments: dict[str, object],
    emit: EventSink,
) -> ToolResult:
    call_id = uuid4()
    emit(
        RuntimeEvent(
            context,
            "tool_started",
            tool_name=name,
            tool_call_id=call_id,
            argument_keys=tuple(sorted(arguments)),
        )
    )
    try:
        result = await executor.execute(context, name, arguments)
    except Exception:
        result = ToolResult({}, code="unavailable")
    emit(
        RuntimeEvent(
            context,
            "tool_finished",
            tool_name=name,
            tool_call_id=call_id,
            code=result.code,
            result_empty=result.empty,
        )
    )
    if name == "present_travel_result" and result.code is None:
        emit(
            RuntimeEvent(
                context,
                "presentation",
                tool_name=name,
                tool_call_id=call_id,
                presentation=result.payload(),
            )
        )
    return result

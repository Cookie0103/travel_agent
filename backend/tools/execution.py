"""共用的工具事件转换；SDK和离线演示走同一业务入口，不负责选择或调度工具。"""

from uuid import uuid4

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeEvent
from backend.tools.contracts import ToolDefinition, ToolExecutor, ToolResult


async def execute_observed(
    executor: ToolExecutor,
    context: RunContext,
    name: str,
    arguments: dict[str, object],
    emit: EventSink,
    *,
    definition: ToolDefinition | None = None,
) -> ToolResult:
    call_id = uuid4()
    properties = definition.schema.get("properties", {}) if definition else {}
    known = properties.keys() if isinstance(properties, dict) else ()
    # 不变量：未知参数名也可能包含私密全文；仅导出服务端schema中已知字段。
    keys = tuple(sorted(key for key in arguments if key in known))
    safe_name = definition.name if definition and definition.name == name else "unregistered"
    emit(
        RuntimeEvent(
            context,
            "tool_started",
            tool_name=safe_name,
            tool_call_id=call_id,
            argument_keys=keys,
        )
    )
    try:
        result = await executor.execute(context, name, arguments)
    except Exception:
        result = ToolResult({}, code="unavailable")
    revision = result.data.get("request_revision")
    emit(
        RuntimeEvent(
            context,
            "tool_finished",
            tool_name=safe_name,
            tool_call_id=call_id,
            code=result.code,
            result_empty=result.empty,
            request_revision=revision
            if isinstance(revision, int) and not isinstance(revision, bool)
            else None,
            evidence_ids=result.evidence_ids,
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

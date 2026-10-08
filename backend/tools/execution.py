"""共用的工具事件转换；SDK和离线演示走同一业务入口，不负责选择或调度工具。"""

import json
import time
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError

from backend.agent.runtime import EventSink
from backend.domain.execution import BusinessResult, RunContext, RuntimeEvent
from backend.tools.contracts import ToolDefinition, ToolExecutor, ToolResult
from backend.trace_log import trace

_CALLS: dict[UUID, int] = {}  # 仅用于TRACE的调用序号，按run计数


def _chars(result: ToolResult) -> int:
    try:
        return len(json.dumps(result.payload(), ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return -1


def stage_result(result: ToolResult) -> BusinessResult | None:
    if result.code:
        reason = next(
            (v for v in result.detail if v in {"plan_exists", "patch_invalid", "repair_limit"}),
            "other",
        )
        return TypeAdapter(BusinessResult).validate_python(
            {"kind": "stage_failed", "code": result.code, "reason": reason}
        )
    report = result.data.get("validation")
    if not isinstance(report, dict):
        return None
    try:
        return TypeAdapter(BusinessResult).validate_python(
            {
                "kind": "draft_staged",
                "draft_id": result.data.get("draft_id"),
                "plan_id": result.data.get("plan_id"),
                "validation_status": report.get("status"),
            }
        )
    except ValidationError:
        return None


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
    if len(_CALLS) > 256:
        _CALLS.clear()
    index = _CALLS[context.run_id] = _CALLS.get(context.run_id, 0) + 1
    trace("tool_start", context.run_id, name=safe_name, call_index=index)
    started, error_class = time.monotonic(), None
    try:
        result = await executor.execute(context, name, arguments)
    except Exception as error:
        error_class = type(error).__name__
        result = ToolResult({}, code="unavailable")
    trace(
        "tool_end",
        context.run_id,
        name=safe_name,
        call_index=index,
        code=result.code,
        elapsed_ms=round((time.monotonic() - started) * 1000),
        result_chars=_chars(result),
        timed_out=result.code == "timeout",
        limit_s=definition.timeout_seconds if definition else None,
        error_class=error_class,
        detail=list(result.detail) if result.detail else None,
    )
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
            business_result=stage_result(result) if safe_name == "stage_plan_change" else None,
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

"""共用的工具事件转换；SDK和离线演示走同一业务入口，不负责选择或调度工具。"""

import json
import time
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError

from backend.agent.runtime import EventSink
from backend.domain.execution import BusinessResult, RunContext, RuntimeEvent, tool_reason
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
        # 重复被拒的调用保留原始标签(repeat_blocked之后)，业务结果仍给出原因。
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


def empty_hotel_payload(result: ToolResult) -> dict[str, object]:
    """仅投影可信类别；不回显异常/参数/任意建议，不进行酒店比较。"""
    reasons = {
        None: "没有找到符合当前条件的酒店报价；请在对话中调整条件后重试。",
        "validation": "查询条件或参数尚不完整；请在对话中补充或核对。",
        "blocked": "报价不存在、不属于当前旅行或操作不被允许；请重新查询。",
        "unavailable": "酒店查询服务暂不可用；请稍后重试。",
        "timeout": "酒店查询超时；请稍后重试。",
        "rate_limited": "酒店查询请求受限；请稍后重试。",
        "provider_error": "酒店数据服务返回错误；请稍后重试。",
        "conflict": "旅行条件或引用已变化；请核对当前条件后重新查询。",
        "cancelled": "酒店查询已取消；需要时可重新查询。",
    }
    reason = reasons[result.code]
    if result.code == "conflict" and "lodging_budget_conflict" in result.detail:
        reason = "住宿预算下限超过全程预算，暂不能比较酒店。请在对话中确认以哪个为准。"
    if result.code == "validation" and "hotel_search_location_required" in result.detail:
        reason = (
            "目的地范围较大，请在对话中提供具体住宿城市或地点；"
            "已记录的日期、人数和房型无需重复填写。"
        )
    return {
        **result.payload(),
        "data": {
            "component": "hotel_comparison",
            "cards": [],
            "comparison": {
                "budget_relation": None,
                "comparable": False,
                "lowest_offer_ids": [],
                "scope": "本轮没有可展示的酒店报价，未进行价格比较。",
                "reasons": [reason],
            },
        },
        "evidence_ids": [],
        "warnings": [],
        "error": {"code": result.code, "suggestion": reason} if result.code else None,
    }


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
            reason=tool_reason(result.code, result.detail),
            result_empty=result.empty,
            request_revision=revision
            if isinstance(revision, int) and not isinstance(revision, bool)
            else None,
            evidence_ids=result.evidence_ids,
            business_result=stage_result(result) if safe_name == "stage_plan_change" else None,
        )
    )
    payload = None
    if safe_name == "present_travel_result" and result.code is None:
        payload = result.payload()
    elif (
        safe_name in {"search_hotel_offers", "refresh_hotel_offer"}
        and (result.empty or result.code is not None)
    ) or (
        safe_name == "present_travel_result"
        and arguments.get("component") == "hotel_comparison"
        and result.code is not None
    ):
        payload = empty_hotel_payload(result)
    if payload is not None:
        emit(
            RuntimeEvent(
                context,
                "presentation",
                tool_name=name,
                tool_call_id=call_id,
                presentation=payload,
            )
        )
    return result

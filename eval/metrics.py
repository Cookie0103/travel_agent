"""逐调用证据与首次有效进度；缺语义参数证明时unknown，不把工具成功当准确率。"""

from collections import Counter
from datetime import datetime

from pydantic import ValidationError

from backend.domain.execution import RunContext, RuntimeEvent
from backend.tools.travel import SCHEMAS
from eval.cases import Case
from eval.diagnostics import ArgumentFact, bind_call


def first_progress_seconds(
    started_at: datetime,
    finished_at: datetime,
    context: RunContext,
    events: tuple[RuntimeEvent, ...],
) -> float | None:
    # text未经过语义分类，可能只是ACK；仅自动计工具进度/卡片，纯文本进度保持未知。
    meaningful = [
        e
        for e in events
        if e.context == context and e.kind in {"tool_started", "tool_finished", "presentation"}
    ]
    if not meaningful or started_at.utcoffset() is None or finished_at.utcoffset() is None:
        return None
    if any(
        e.occurred_at.utcoffset() is None or not started_at <= e.occurred_at <= finished_at
        for e in meaningful
    ):
        return None
    return (min(e.occurred_at for e in meaningful) - started_at).total_seconds()


def parameters_correct(
    name: str,
    actual: ArgumentFact,
    expected: ArgumentFact | None,
) -> bool | None:
    schema = SCHEMAS.get(name)
    if schema is None:
        return None
    try:
        parsed = schema.model_validate(actual.arguments).model_dump(mode="json")
    except ValidationError:
        return False
    if expected is None or (actual.context, actual.tool_call_id) != (
        expected.context,
        expected.tool_call_id,
    ):
        return None
    try:
        target = schema.model_validate(expected.arguments).model_dump(mode="json")
    except ValidationError:
        return None  # 无效评测答案不能证明模型错，也不能充当成功。
    return parsed == target


def tool_call_accuracy(
    case: Case,
    events: tuple[RuntimeEvent, ...],
    facts: tuple[ArgumentFact, ...] = (),
    expectations: tuple[ArgumentFact, ...] = (),
) -> dict[str, object]:
    """expected是独立既定答案，actual是私有事实；只输出脱敏判定，不输出参数。"""
    starts = [e for e in events if e.kind == "tool_started"]
    ends = [e for e in events if e.kind == "tool_finished"]
    ids = Counter(e.tool_call_id for e in starts)
    consistent = len(starts) == len(ends) and None not in ids and all(n == 1 for n in ids.values())
    calls: list[dict[str, object]] = []
    for start in starts:
        attachments = [
            f for f in facts if f.context == start.context and f.tool_call_id == start.tool_call_id
        ]
        targets = [
            f
            for f in expectations
            if f.context == start.context and f.tool_call_id == start.tool_call_id
        ]
        pair = (
            bind_call(events, ArgumentFact(start.context, start.tool_call_id, {}))
            if start.tool_call_id
            else None
        )
        consistent &= pair is not None
        selected = (
            start.tool_name in case.allowed_tools and start.tool_name not in case.forbidden_tools
        )
        arguments: bool | None = None
        if pair is not None and len(attachments) == 1:
            arguments = parameters_correct(
                start.tool_name or "", attachments[0], targets[0] if len(targets) == 1 else None
            )
        correct = (
            False if not selected or arguments is False else True if arguments is True else None
        )
        calls.append(
            {
                "call_id": str(start.tool_call_id) if start.tool_call_id else None,
                "tool": start.tool_name if start.tool_name in SCHEMAS else "unregistered",
                "selection_correct": selected,
                "parameters_correct": arguments,
                "correct": correct,
            }
        )
    counts = {
        "correct": sum(c["correct"] is True for c in calls),
        "incorrect": sum(c["correct"] is False for c in calls),
        "unknown": sum(c["correct"] is None for c in calls),
    }
    return {
        "total": len(starts),
        **counts,
        "events_consistent": consistent,
        "accuracy": counts["correct"] / len(starts)
        if starts and consistent and not counts["unknown"]
        else None,
        "calls": calls,
        "basis": "allowed paths plus complete independent parameter expectations; "
        "successful tool return alone is insufficient",
    }

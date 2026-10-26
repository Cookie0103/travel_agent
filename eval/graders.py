"""规则评分只看实际事件和最终输出；语义正确性需后续人工/模型校准。"""

import re
from dataclasses import dataclass

from backend.domain.execution import RuntimeEvent
from eval.cases import Case

# 旧轨迹里模型的propose_memory与现行run后异步抽取(memory_extractor)都是记忆卡来源。
MEMORY_SOURCES = frozenset({"propose_memory", "memory_extractor"})


@dataclass(frozen=True)
class Observation:
    status: str
    text: str
    events: tuple[RuntimeEvent, ...]


def memory_presentations_allowed(events: tuple[RuntimeEvent, ...]) -> bool:
    success = {
        (e.context, e.tool_call_id)
        for e in events
        if e.kind == "tool_finished" and e.code is None and e.result_empty is False
    }
    proposed: dict[tuple[object, str], int] = {}
    displays: dict[tuple[object, object], bool] = {}
    for index, event in enumerate(events):
        call = (event.context, event.tool_call_id)
        if event.tool_name == "present_travel_result" and event.kind == "tool_started":
            displays[call] = False
        if event.kind != "presentation" or call not in success:
            continue
        data = event.presentation.get("data") if isinstance(event.presentation, dict) else None
        if (
            not isinstance(data, dict)
            or data.get("component") != "choice"
            or data.get("kind") != "memory_confirm"
            or not isinstance(data.get("choice_id"), str)
        ):
            continue
        card = (event.context, str(data["choice_id"]))
        if event.tool_name in MEMORY_SOURCES:
            proposed[card] = index
        elif event.tool_name == "present_travel_result" and call in displays and card in proposed:
            started = next(
                i
                for i, e in enumerate(events)
                if e.kind == "tool_started" and (e.context, e.tool_call_id) == call
            )
            displays[call] = proposed[card] < started
    return bool(displays) and all(displays.values())


def grade(case: Case, actual: Observation) -> dict[str, bool]:
    started = [e for e in actual.events if e.kind == "tool_started"]
    finished = [e for e in actual.events if e.kind == "tool_finished"]
    names = {e.tool_name for e in started}
    allowed = set(case.allowed_tools)
    if case.memory_category and memory_presentations_allowed(actual.events):
        allowed.add("present_travel_result")
    # 不变量：仅启动工具不能当成查到结果，空数据和工具异常也不是结果。
    starts = {e.tool_call_id: e.tool_name for e in started}
    ends = {e.tool_call_id: e.tool_name for e in finished}
    complete = (
        starts == ends
        and None not in starts
        and len(starts) == len(started)
        and len(ends) == len(finished)
    )
    has_results = complete and any(
        e.code is None
        and e.result_empty is False
        and (not case.result_tools or e.tool_name in case.result_tools)
        for e in finished
    )
    return {
        "completed": actual.status in case.allowed_final_statuses and bool(actual.text.strip()),
        "tool_selection": set(case.required_tools) <= names,
        "no_unnecessary_tools": names <= allowed,
        # 故障前允许合法读取；实际故障仍须通过独立业务断言，不能用空结果代替。
        "has_results": case.result_requirement == "optional"
        or has_results == case.should_have_results,
        "no_forbidden_tool": not names.intersection(case.forbidden_tools),
        "tool_success": complete
        and all(
            e.code in case.expected_tool_errors
            if e.code is not None
            else e.result_empty is not None
            for e in finished
        ),
        "response_rule": response_matches(case.response_rule, actual.text),
    }


def response_matches(rule: str, text: str) -> bool:
    """弱规则只检查明确表述，不能证明事实准确或建议相关；报告按规则分命名。"""
    if rule == "clarify":
        return bool(re.search(r"[?？]|请.{0,8}(告诉|提供)|什么|哪[里个天种]|偏好", text))
    if rule == "unsupported":
        return "京都" in text and bool(
            re.search(
                r"(?:只|仅)(?:能)?(?:提供|支持|覆盖|服务).{0,12}京都|"
                r"(?:暂不|不)支持|(?:暂时|目前)无法|不在.{0,8}(?:服务|支持)范围",
                text,
            )
        )
    if rule == "out_of_scope":
        return bool(re.search(r"旅行|旅游|京都", text)) and bool(re.search(r"不|只|范围", text))
    return bool(text.strip())

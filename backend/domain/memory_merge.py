"""合并记忆确认卡的候选：只从“用户已提交的合并选择卡答案”推导，不信模型、不做语义猜测。

可长期的只有 节奏/交通/平时起床/晚上结束（见 domain.memory.LONG_TERM_ELIGIBLE）；
“无要求/不确定”不是偏好；用户事后在对话里改了这次的值（request 与卡片答案不再一致）就不提议。
"""

import re
from dataclasses import dataclass

from backend.domain.choices import PACE_BY_OPTION, PREFIXES, ChoiceForm
from backend.domain.memory import MemoryKey
from backend.domain.travel_request import TravelRequest, pace_of

# 合并选择卡的组 -> 记忆键
GROUP_KEYS: dict[str, MemoryKey] = {
    "pace": "pace",
    "transport": "transport",
    "wake": "wake_time",
    "evening": "evening_end",
}
_CLOCK = re.compile(r"\d[:：]\d{2}|\d\s*[点時时]")


@dataclass(frozen=True)
class Candidate:
    key: MemoryKey
    value: str
    quote: str  # 证据：用户在卡片上的答案文字，如“旅行节奏：特种兵”


def card_candidates(form: ChoiceForm, request: TravelRequest) -> tuple[Candidate, ...]:
    """已回答的合并卡 -> 仍与当前 request 一致的可长期偏好。"""
    found: list[Candidate] = []
    for group in form.groups:
        key = GROUP_KEYS.get(group.key)
        if key is None:
            continue
        labels = {option.option_id: option.label for option in group.options}
        choice = group.selected[0] if group.selected else ""
        typed = (group.text or "").strip()
        if choice == "any" or not (choice or typed):
            continue
        value: str | None
        if group.key == "pace":
            value = PACE_BY_OPTION.get(choice)
            if value is None or pace_of(request) != value:
                continue
            shown = labels[choice]
        elif group.key == "transport":
            if choice not in {"walk", "transit", "taxi"} or request.transport != choice:
                continue
            value, shown = choice, labels[choice]
        else:
            shown = typed or labels.get(choice, "")
            if not shown or not _CLOCK.search(shown):  # “看情况”之类不是可复用的时间
                continue
            prefix = PREFIXES[group.key][0]
            if prefix + shown not in (*request.soft_constraints, *request.hard_constraints):
                continue
            value = shown
        assert value is not None
        found.append(Candidate(key, value, f"{group.label}：{shown}"))
    return tuple(found)

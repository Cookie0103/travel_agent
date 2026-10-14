"""对实际事件与回答中的卡片/重试/过期断言做确定性粗检；不调用评审模型。"""

import re
from collections.abc import Sequence
from datetime import datetime

from backend.domain.execution import RuntimeEvent

CLAIM_WORDS = {
    "card": ("预算确认卡", "记忆确认卡", "确认卡", "选择卡", "酒店比较卡"),
    "retry": ("自动重试", "已重试", "已尝试"),
    "expiry": ("已过期", "已经过期"),
    "negative": (
        "没有",
        "未出现",
        "未生成",
        "不存在",
        "不能",
        "不再",
        "无需",
        "并未",
        "未进行",
        "不用",
        "不需要",
        "不要",
        "不必",
    ),
    "future": ("若以后", "如果以后", "以后有", "将来", "稍后重试", "需要我", "可以重试"),
    "history": ("上轮", "上一轮", "之前", "历史"),
}
NUMBERS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}


def clause_prefix(sentence: str, position: int) -> str:
    return re.split(r"[，,：:]|但是|不过|然而|但|却", sentence[:position])[-1]


def asserted(sentence: str, position: int) -> bool:
    prefix = clause_prefix(sentence, position)
    return not any(w in prefix for w in CLAIM_WORDS["negative"]) and not any(
        w in sentence[:position] for w in CLAIM_WORDS["future"]
    )


def claim_consistency(
    answer: str,
    events: tuple[RuntimeEvent, ...],
    *,
    answered_at: datetime | None = None,
    valid_until: Sequence[datetime] = (),
) -> dict[str, bool | None]:
    results: dict[str, bool | None] = {"card": True, "retry": True, "expiry": True}
    presentations = [e.presentation.get("data") for e in events if isinstance(e.presentation, dict)]
    cards = [d for d in presentations if isinstance(d, dict) and d.get("component") == "choice"]
    hotels = any(
        isinstance(d, dict)
        and d.get("component") == "hotel_comparison"
        and (d.get("cards") or d.get("segments"))
        for d in presentations
    )
    attempts = [
        e.external.attempts
        for e in events
        if e.kind == "tool_finished"
        and e.tool_name == "search_hotel_offers"
        and e.external is not None
    ]
    for sentence in re.split(r"[。！？\n；]", answer):
        for match in re.finditer("|".join(CLAIM_WORDS["card"]), sentence):
            word, position = match.group(), match.start()
            if not asserted(sentence, position):
                continue
            if any(w in clause_prefix(sentence, position) for w in CLAIM_WORDS["history"]):
                if results["card"] is not False:
                    results["card"] = None
                continue
            kind = {"预算确认卡": "budget_relaxation", "记忆确认卡": "memory_confirm"}.get(word)
            supported = any(d.get("kind") == kind for d in cards) if kind else bool(cards) or hotels
            if not supported:
                results["card"] = False
        for match in re.finditer(
            r"(自动重试|已重试)\s*([零一二两三四五\d]+)?\s*次?|"
            r"(已尝试)\s*([零一二两三四五\d]+)\s*次",
            sentence,
        ):
            if not asserted(sentence, match.start()):
                continue
            token = match.group(2) or match.group(4)
            number = int(token) if token and token.isdecimal() else NUMBERS.get(token or "", 1)
            possible = {v if match.group(3) == "已尝试" else max(0, v - 1) for v in attempts}
            if not possible:
                if results["retry"] is not False:
                    results["retry"] = None
            elif number not in possible:
                results["retry"] = False
        for word in CLAIM_WORDS["expiry"]:
            position = sentence.find(word)
            if position < 0 or not asserted(sentence, position):
                continue
            if answered_at is None or not valid_until:
                if results["expiry"] is not False:
                    results["expiry"] = None
            elif all(t > answered_at for t in valid_until):
                results["expiry"] = False
            elif not all(t <= answered_at for t in valid_until):
                results["expiry"] = None
    results["passed"] = (
        False
        if any(v is False for v in results.values())
        else None
        if any(v is None for v in results.values())
        else True
    )
    return results

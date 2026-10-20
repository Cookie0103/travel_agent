"""对实际事件与回答中的卡片/重试/过期断言做确定性粗检；不调用评审模型。"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from backend.domain.execution import RuntimeEvent

CLAIM_SCORER_VERSION = "claims-v6-facts"

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
        "不会",
        "无需",
        "并未",
        "未进行",
        "不用",
        "不需要",
        "不要",
        "不必",
    ),
    "future": (
        "若以后",
        "如果以后",
        "以后有",
        "将来",
        "稍后重试",
        "需要我",
        "可以重试",
        "可以展示",
        "要现在展示",
        "若已过期",
        "如果已过期",
    ),
    "history": ("上轮", "上一轮", "之前", "历史"),
}
FACT_CLAIMS = {
    "budget": re.compile(
        r"在预算(?:内|范围内)|预算范围内|符合预算|满足预算|低于预算|"
        r"(?:没有|未|不)超(?:出|过)?预算"
    ),
    "hotel_selected": re.compile(
        r"已(?:经)?(?:为你|为您|帮你|帮您)?(?:选定|选择|选好|选了|记录了?)(?:你的|您的|了)?(?:酒店|住宿)|"
        r"已经?选了[^，,。；]{0,12}?(?:酒店|住宿)|"
        r"(?:酒店|住宿)已(?:经)?(?:选定|选择|选好|记录)"
    ),
    "remembered": re.compile(
        r"已(?:经)?(?:为你|为您)?记住|记住了|已(?:经)?保存(?:为|到)?(?:长期)?偏好"
    ),
}
# 不是在断言“已满足”：搜不到/提供选项/提问。命中则跳过该匹配。
ABSENCE_WORDS = ("没有找到", "没找到", "暂无", "没有", "找不到")
OFFER_WORDS = ("可以选择", "可选", "要不要", "是否", "吗")
NUMBERS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}


@dataclass(frozen=True)
class ClaimFacts:
    """服务端实际状态：True=成立，False=不成立，None=无法判断；仅评测传入。"""

    within_budget_cards: bool | None = None
    hotel_selected: bool | None = None
    memory_active: bool | None = None


def clause_prefix(sentence: str, position: int) -> str:
    return re.split(r"[，,：:]|但是|不过|然而|但|却", sentence[:position])[-1]


def asserted(sentence: str, position: int) -> bool:
    prefix = clause_prefix(sentence, position)
    if re.search(r"(?:未|没|不)(?:再)?$", prefix.strip()):
        return False
    return not any(w in prefix for w in CLAIM_WORDS["negative"]) and not any(
        w in sentence[:position] for w in CLAIM_WORDS["future"]
    )


def claim_consistency(
    answer: str,
    events: tuple[RuntimeEvent, ...],
    *,
    answered_at: datetime | None = None,
    valid_until: Sequence[datetime] = (),
    facts: ClaimFacts | None = None,
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
            if re.match(
                r"^\s*(?:在本轮)?(?:的)?(?:状态)?(?:为|是)?[：:\s“”\"]*"
                r"(?:未展示|未生成|未出现|不存在|没有了|none)",
                sentence[match.end() :],
            ):
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
            prefix = clause_prefix(sentence, position)
            if re.search(r"(?:若|如果|假如)(?:报价|价格)?$", prefix.strip()):
                continue
            if any(w in prefix for w in CLAIM_WORDS["history"]):
                if results["expiry"] is not False:
                    results["expiry"] = None
                continue
            if answered_at is None or not valid_until:
                if results["expiry"] is not False:
                    results["expiry"] = None
            elif all(t > answered_at for t in valid_until):
                results["expiry"] = False
            elif not all(t <= answered_at for t in valid_until):
                results["expiry"] = None
    if facts is not None:
        actual = {
            "budget": facts.within_budget_cards,
            "hotel_selected": facts.hotel_selected,
            "remembered": facts.memory_active,
        }
        for name, pattern in FACT_CLAIMS.items():
            results[name] = True
            results[name + "_claimed"] = False
            for sentence in re.findall(r"[^。！？\n；]+[。！？\n；]?", answer):
                question = sentence.endswith("？")
                sentence = sentence.rstrip("。！？\n；")
                for match in pattern.finditer(sentence):
                    if not asserted(sentence, match.start()):
                        continue
                    rest = re.split(r"[，,：:]", sentence[match.end() :])[0]
                    if (
                        question
                        or any(w in rest for w in ABSENCE_WORDS)
                        or any(w in sentence for w in OFFER_WORDS)
                    ):
                        continue
                    results[name + "_claimed"] = True
                    if actual[name] is False:
                        results[name] = False
                    elif actual[name] is None and results[name] is not False:
                        results[name] = None
    results["passed"] = (
        False
        if any(v is False for k, v in results.items() if not k.endswith("_claimed"))
        else None
        if any(v is None for k, v in results.items() if not k.endswith("_claimed"))
        else True
    )
    return results

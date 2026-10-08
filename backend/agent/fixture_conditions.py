"""仅离线演示的有限中文表达；不参与SDK解析，未知不补样例事实。"""

import re
from datetime import date, timedelta
from decimal import Decimal

from backend.domain.travel_request import TravelRequest

NUMBER = r"(?:\d+|十二|十一|十|[一二两三四五六七八九])"
SMALL_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}


def number(text: str) -> int:
    return int(text) if text.isdecimal() else SMALL_NUMBERS[text]


def ambiguous_expression(prompt: str) -> bool:
    return bool(
        re.search(r"如果|可能|也许|考虑|不确定|大概|不要|不想|不改|不清空|不能|暂不", prompt)
        or re.search(r"(?:^|[，,。；;]|请)\s*别(?:改|去|清空|更新|记录|保存)", prompt)
    )


def unsupported_trip_currency(prompt: str) -> bool:
    currencies = re.finditer(
        r"(?:全程(?:预算)?|总预算)(?:改成|改为|是|为)?\s*"
        r"\d+(?:\.\d+)?(?:万|千)?\s*([A-Z]{3}|日元|円|美元|欧元|人民币|元)",
        prompt,
    )
    return any(currency[1] not in ("JPY", "日元", "円") for currency in currencies)


def fixture_patch(prompt: str, request: TravelRequest, today: date) -> dict[str, object]:
    """有限词汇/金额/日期样例输入转工具参数；不扫描历史或第三方资料。"""
    text = prompt.replace("（", "(").replace("）", ")")
    if ambiguous_expression(text) or unsupported_trip_currency(text):
        # 有限离线演示不解释假设/否定的作用域，整句先澄清，不记录候选事实。
        return {
            "expected_revision": request.revision,
            "set": {},
            "clear": [],
            "explicit_fields": [],
        }
    fields: dict[str, object] = {}
    explicit: set[str] = set()
    clear: list[str] = []

    def put(name: str, value: object, match: re.Match[str]) -> None:
        fields[name] = value
        expression = text[max(0, match.start() - 8) : match.end()]
        if re.search(r"改成|改为|改到|改去", expression) and not re.search(
            r"如果|可能|也许|考虑|不确定|大概", text
        ):
            explicit.add(name)

    if city := re.search(
        r"(?:去|目的地(?:改成|改为|是)?)(札幌|京都|东京|東京|大阪|名古屋|福冈|横滨)", text
    ):
        put("city", city[1].replace("東京", "东京"), city)
    if adults := re.search(rf"({NUMBER})(?:个)?(?:大人|成人)", text):
        put("adults", number(adults[1]), adults)
    if children := re.search(r"(?:小孩|儿童)\s*\((\d+)岁\)", text):
        put("child_ages", [int(children[1])], children)
    elif no_children := re.search(r"无儿童|没有儿童|不带儿童", text):
        put("child_ages", [], no_children)
    if rooms := re.search(rf"({NUMBER})(?:间|个)(?:房间|房)", text):
        put("rooms", number(rooms[1]), rooms)
    if budget := re.search(
        r"(?:全程(?:预算)?|总预算)(?:改成|改为|是|为)?\s*(\d+(?:\.\d+)?)(万|千)?", text
    ):
        factor = {"万": 10000, "千": 1000, None: 1}[budget[2]]
        put("budget", str(Decimal(budget[1]) * factor), budget)
    if lodging := re.search(
        r"(?:酒店|住宿)(?:预算)?(每房每晚|每晚|总额|总共)(?:改成|改为|是|为)?\s*"
        r"(\d+(?:\.\d+)?)(?:[–—\-到至](\d+(?:\.\d+)?))?(万|千)?"
        r"(?:\s*([A-Z]{3}|日元|美元|欧元|人民币))?",
        text,
    ):
        factor = {"万": 10000, "千": 1000, None: 1}[lodging[4]]
        put(
            "lodging_budget",
            {
                "amount": {
                    "lower": str(Decimal(lodging[2]) * factor),
                    "upper": str(Decimal(lodging[3] or lodging[2]) * factor),
                },
                "basis": "per_room_night" if "每" in lodging[1] else "total",
                "currency": {"日元": "JPY", "美元": "USD", "欧元": "EUR", "人民币": "CNY"}.get(
                    lodging[5], lodging[5] or request.currency
                ),
            },
            lodging,
        )
    if weekend := re.search(r"下周末", text):
        saturday = today + timedelta(days=7 - today.weekday() + 5)
        put("start_date", saturday.isoformat(), weekend)
        put("end_date", (saturday + timedelta(days=1)).isoformat(), weekend)
    elif dates := re.search(r"(\d{4}-\d{2}-\d{2})(?:到|至|—|~)(\d{4}-\d{2}-\d{2})", text):
        put("start_date", dates[1], dates)
        put("end_date", dates[2], dates)
    if pace := re.search(r"特种兵|慢节奏|标准节奏", text):
        # 只替换现有节奏，不丢用户的其他软条件。
        put(
            "soft_constraints",
            [
                c
                for c in request.soft_constraints
                if not c.startswith("节奏：") and c not in ("特种兵", "慢节奏", "标准")
            ]
            + ["节奏：" + ("标准" if pace[0] == "标准节奏" else pace[0])],
            pace,
        )
    for name, label in (("budget", "全程预算"), ("lodging_budget", "住宿预算")):
        if re.search(rf"清空{label}|{label}(?:清空|改为未知)", text):
            fields.pop(name, None)
            clear.append(name)
            explicit.add(name)
    return {
        "expected_revision": request.revision,
        "set": fields,
        "clear": clear,
        "explicit_fields": sorted(explicit),
    }


def missing_question(request: TravelRequest) -> str:
    labels = {
        "city": "目的地",
        "start_date": "开始日期",
        "end_date": "结束日期",
        "adults": "成人数",
        "child_ages": "儿童年龄（或明确无儿童）",
        "rooms": "房间数",
    }
    missing = [labels[k] for k in request.hotel_requirements() if k in labels]
    if missing:
        return "请在对话里补充：" + "、".join(missing) + "。"
    if not request.soft_constraints:
        return "旅行条件已记录。你想要标准、慢节奏还是特种兵节奏？"
    return "旅行条件已记录。接下来想比较酒店，还是生成行程？"

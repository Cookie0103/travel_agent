"""仅离线演示的有限中文表达；不参与SDK解析，未知不补样例事实。"""

import re
from datetime import date, timedelta
from decimal import Decimal

from backend.domain.conversation import Task, task_missing
from backend.domain.room_preferences import room_preferences_question
from backend.domain.travel_request import TravelRequest

NUMBER = (
    r"(?<![\d.\-一二两三四五六七八九十零〇百千万亿])"
    r"(?:\d+|十二|十一|十|[一二两三四五六七八九])"
    r"(?![\d.一二两三四五六七八九十零〇百千万亿])"
)
CITIES = r"札幌|京都|东京|東京|大阪|名古屋|福冈|横滨"
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


def room_updates(text: str) -> list[tuple[str, str, re.Match[str]]] | None:
    """返回明确分组与原匹配位置；None表示已识别矛盾，runtime必须先澄清。"""
    updates: list[tuple[str, str, re.Match[str]]] = []
    all_free = re.search(r"房型(?:改为|改成)?无要求", text)
    for prefix, pattern, values in (
        (
            "住宿：",
            r"(?:住宿(?:改为|改成)?\s*)?(独立房间|接受宿舍|接受舱房|住宿无要求)",
            {"住宿无要求": "无要求"},
        ),
        ("房型：", r"(?:房型(?:改为|改成)?\s*)?(禁烟无要求|禁烟)", {"禁烟无要求": "无要求"}),
        ("床型：", r"(?:床型(?:改为|改成)?\s*)?(床型无要求|双床|大床)", {"床型无要求": "无要求"}),
    ):
        matches = list(re.finditer(pattern, text))
        found = {values.get(match[1], match[1]) for match in matches}
        if len(found) > 1 or (all_free and found - {"无要求"}):
            return None
        if all_free:
            updates.append((prefix, "无要求", all_free))
        elif matches:
            match = matches[-1]
            updates.append((prefix, values.get(match[1], match[1]), match))
    return updates


def ambiguous_expression(prompt: str) -> bool:
    return bool(
        re.search(
            r"如果|可能|也许|考虑|不确定|大概|不要|不用|不需要|无需|不要求|不想|不改|不清空|不能|暂不|不去|或|还是|二选一|不是|举例|只是提到",
            prompt,
        )
        or re.search(r"(?:^|[，,。；;]|请)\s*别(?:改|去|清空|更新|记录|保存)", prompt)
        or len(set(re.findall(CITIES, prompt.replace("東京", "东京")))) > 1
        or room_updates(prompt) is None
        or re.search(
            r"[\d一二两三四五六七八九十零百千万]+(?:个|间)?(?:大人|成人|人|房间|房)?\s*"
            r"(?:到|至|[-–—~])\s*[\d一二两三四五六七八九十零百千万]+(?:个|间)?(?:大人|成人|人(?!民|均)|房间|房)",
            prompt,
        )
    )


def unsupported_trip_currency(prompt: str) -> bool:
    currencies = re.finditer(
        r"(?:全程(?:预算)?|总预算)(?:改成|改为|是|为)?\s*"
        r"\d+(?:\.\d+)?(?:万|千)?\s*([A-Z]{3}|日元|円|美元|欧元|人民币|元)",
        prompt,
    )
    return any(currency[1] not in ("JPY", "日元", "円") for currency in currencies)


def fixture_patch(
    prompt: str,
    request: TravelRequest,
    today: date,
    *,
    protect_hard_constraints: bool = False,
    awaiting_field: str | None = None,
) -> dict[str, object]:
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

    def is_explicit(match: re.Match[str]) -> bool:
        return bool(
            re.search(r"改成|改为|改到|改去", match[0])
            or re.search(r"(?:改成|改为|改到|改去)\s*$", text[: match.start()])
            or text[max(0, match.start() - 1) : match.start() + 1] == "改去"
        )

    def put(name: str, value: object, match: re.Match[str]) -> None:
        fields[name] = value
        if is_explicit(match):
            explicit.add(name)

    city = re.search(rf"(?:去|目的地(?:改成|改为|是)?\s*[:：]?\s*)({CITIES})", text) or re.search(
        rf"^\s*({CITIES})(?=$|[，,。；;\s])", text
    )
    if city:
        put("city", city[1].replace("東京", "东京"), city)
    adults = re.search(rf"({NUMBER})(?:个)?(?:大人|成人)", text) or re.search(
        rf"(?:大人|成人)(?:数)?(?:改成|改为|是|为|[:：])\s*({NUMBER})(?:个)?人?(?=$|[\s，,。；;])",
        text,
    )
    if adults:
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
    lodging_text = text
    if awaiting_field == "lodging_budget" and re.fullmatch(
        r"\s*\d+(?:\.\d+)?(?:[–—\-到至]\d+(?:\.\d+)?)?(?:万|千)?"
        r"(?:\s*(?:[A-Z]{3}|日元|美元|欧元|人民币))?\s*",
        text,
    ):
        lodging_text = "住宿每晚" + text.strip()
    if lodging := re.search(
        r"(?:酒店|住宿)(?:预算)?(每间房每晚|每房每晚|每晚|总额|总共)(?:改成|改为|是|为)?\s*"
        r"(\d+(?:\.\d+)?)(?:[–—\-到至](\d+(?:\.\d+)?))?(万|千)?"
        r"(?:\s*([A-Z]{3}|日元|美元|欧元|人民币))?",
        lodging_text,
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
        if awaiting_field == "lodging_budget":
            explicit.add("lodging_budget")
        if request.lodging_budget_unlimited:
            clear.append("lodging_budget_unlimited")
            if is_explicit(lodging) or awaiting_field == "lodging_budget":
                explicit.add("lodging_budget_unlimited")
    unlimited = re.search(
        r"(?:住宿|酒店)(?:预算)?(?:改成|改为|是|为)?\s*(不限|无上限|没有(?:单独)?上限)", text
    )
    if awaiting_field == "lodging_budget" and unlimited is None:
        unlimited = re.search(r"^\s*(不限|无上限|没有上限)\s*[。！]?$", text)
    if unlimited:
        if "lodging_budget" in fields:
            return {
                "expected_revision": request.revision,
                "set": {},
                "clear": [],
                "explicit_fields": [],
            }
        put("lodging_budget_unlimited", True, unlimited)
        if awaiting_field == "lodging_budget":
            explicit.add("lodging_budget_unlimited")
        if request.lodging_budget is not None:
            clear.append("lodging_budget")
            if is_explicit(unlimited) or awaiting_field == "lodging_budget":
                explicit.add("lodging_budget")
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
    constraints = list(request.hard_constraints)
    updates = room_updates(text)
    assert updates is not None  # 入口ambiguous_expression已拦截；不得空patch落入查询。
    any_explicit = any(is_explicit(match) for _, _, match in updates)
    for prefix, value, match in updates:
        if protect_hard_constraints and any_explicit and not is_explicit(match):
            continue
        constraints = [c for c in constraints if not c.startswith(prefix)] + [prefix + value]
        put("hard_constraints", constraints.copy(), match)
    for name, label in (("budget", "全程预算"), ("lodging_budget", "住宿预算")):
        if re.search(rf"清空{label}|{label}(?:清空|改为未知)", text):
            if name == "lodging_budget" and (
                "lodging_budget" in fields or "lodging_budget_unlimited" in fields
            ):
                return {
                    "expected_revision": request.revision,
                    "set": {},
                    "clear": [],
                    "explicit_fields": [],
                }
            fields.pop(name, None)
            clear.append(name)
            explicit.add(name)
            if name == "lodging_budget" and request.lodging_budget_unlimited:
                fields.pop("lodging_budget_unlimited", None)
                clear.append("lodging_budget_unlimited")
                explicit.add("lodging_budget_unlimited")
    return {
        "expected_revision": request.revision,
        "set": fields,
        "clear": clear,
        "explicit_fields": sorted(explicit),
    }


def missing_question(request: TravelRequest, *, task: Task | None = None) -> str:
    if task == "itinerary" and "lodging_budget" in task_missing(request, task):
        return "每间房每晚的住宿预算上限是多少日元？也可以明确回答不限。"
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
    if not any(
        c in ("节奏：标准", "节奏：慢节奏", "节奏：特种兵") for c in request.soft_constraints
    ):
        return "旅行条件已记录。你想要标准、慢节奏还是特种兵节奏？"
    if question := room_preferences_question(request):
        return question
    return "旅行条件已记录。接下来想比较酒店，还是生成行程？"

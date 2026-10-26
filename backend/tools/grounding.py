"""explicit_fields 声明的出处核对：新值必须能在本轮可信用户原话里找到常见写法。

模型自填 explicit_fields 会绕过手填保护；这里按字段做保守的文本核对（同记忆提议引用核验的
“引用必须来自本轮用户原话”思路）。核对不过的字段按“未声明”处理，由服务端来源保护生效。
宁可让模型多问一句，也不让攻略/供应商文本诱导改写手填条件；放宽规则见各函数注释。
"""

import calendar
import re
import unicodedata
from collections.abc import Callable
from datetime import date, time, timedelta
from decimal import Decimal
from typing import Any

from backend.domain.room_choices import recognized_room_choices
from backend.domain.travel_request import (
    CITY_ALIASES,
    ConversationRequestPatch,
    LodgingBudget,
    TravelRequest,
    TripSegment,
)

_DIGITS = {c: i for i, c in enumerate("零一二三四五六七八九")} | {"〇": 0, "两": 2}
_NUM = r"\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千]+"
# 数字token只能从“数字串起点”开始匹配：否则在长数字串上每个起点都要回溯一遍，退化成二次方。
_N = rf"(?<![\d.零〇一二两三四五六七八九十百千])(?:{_NUM})"


def _compact(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split()).casefold()


def _cn_small(token: str) -> int | None:
    """0-9999的中文数字（含“十五”“两百”）；非法返回None。"""
    if not token:
        return None
    total, current = 0, 0
    for char in token:
        if char in _DIGITS:
            current = _DIGITS[char]
        elif char in "十百千":
            unit = {"十": 10, "百": 100, "千": 1000}[char]
            total, current = total + (current or 1) * unit, 0
        else:
            return None
    return total + current


def _integer(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _cn_small(token)


_CURRENCY = re.compile(r"日元|日圆|日幣|円|元|块|yen|jpy|rmb|cny|人民币|美元|usd|dollars?")
_NOT_MONEY_NEXT = frozenset("月日号点时人位间晚天夜岁周年个口:/-小分秒")
_BUDGET_CUE = re.compile(
    r"(?:预算|budget|总价|费用|价格|price|人均|最多|最高|不超过|上限|每晚|一晚|[¥￥$])"
    r"[^\d零〇一二两三四五六七八九十百千]{0,3}$"
)
_AMOUNT_TOKEN = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)(万|千|百|k(?![a-z])|w(?![a-z]))?"
    r"|(?<![\d零〇一二两三四五六七八九十百千])([零〇一二两三四五六七八九十百千]+)(万)?([一二三四五六七八九])?"
)


def _money_context(text: str, start: int, end: int, has_unit: bool) -> bool:
    """金额必须带金额语境：货币词/符号、万千k/w单位，或紧跟“预算/最多…”；
    紧跟月日号点时人位间晚天等的数字是日期/时间/人数/天数片段，不算金额。"""
    if _CURRENCY.match(text, end) or text[max(start - 1, 0) : start] in ("¥", "￥", "$"):
        return True
    if text[end : end + 1] in _NOT_MONEY_NEXT:
        return False
    return has_unit or bool(_BUDGET_CUE.search(text[max(start - 8, 0) : start]))


def _amounts(text: str) -> set[Decimal]:
    """文本里以金额写法出现的数值：千分位、万/千/k/w 后缀与中文数字（“三万五”=35000）。"""
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)  # 只去千分位逗号，子句逗号保留
    units = {"万": 10000, "w": 10000, "千": 1000, "k": 1000, "百": 100}
    found: set[Decimal] = set()
    for m in _AMOUNT_TOKEN.finditer(text):
        raw, unit, cn, wan, tail = m.groups()
        if raw:
            if _money_context(text, m.start(), m.end(), bool(unit)):
                found.add(Decimal(raw) * units.get(unit, 1))
        elif (small := _cn_small(cn)) is not None and _money_context(
            text, m.start(), m.end(), bool(wan)
        ):
            found.add(Decimal(small * 10000 + _DIGITS.get(tail, 0) * 1000 if wan else small))
    return found


_NEGATION = re.compile(
    r"(?:不要|不去|不想|不用|不是|不到|不在|不住|不考虑|不选|(?<![特分区告辞道惜性差识辨])别"
    r"|除了|除去|避开|排除|不含)[去到在住逛玩看选]{0,2}$"
)
_CLAUSE_BREAK = re.compile(r"[，,。；;！!？?]")


def _affirmed(name: str, text: str) -> bool:
    """name 在文本里至少有一处不在否定/排除语境（“不要去X”“除了X”）里。"""
    start = text.find(name)
    while start >= 0:
        head = _CLAUSE_BREAK.split(text[max(start - 8, 0) : start])[-1]
        if not _NEGATION.search(head):
            return True
        start = text.find(name, start + 1)
    return False


def _city(value: str, text: str) -> bool:
    key = _compact(value).removesuffix("市")
    names = {key} | {alias for alias, canonical in CITY_ALIASES.items() if canonical == key}
    names |= {_compact(canonical) for alias, canonical in CITY_ALIASES.items() if alias == key}
    return any(name and _affirmed(name, text) for name in names)


_DURATION = re.compile(rf"{_N}\s*(?:天|晚|夜|日游)|(?<![\d.])\d+\s*(?:days?|nights?)")
_WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_SHIFT = {"下下": 2, "下": 1, "这": 0, "本": 0}
_WEEKLY = re.compile(r"(?<![上每])(下下|下|这|本)?个?(?:周|星期|礼拜)([一二三四五六日天末])")
_MONTH_DAY = re.compile(rf"(下下|下|这|本)个?月({_N})[号日]")
_MONTH_EDGE = re.compile(r"(下下|下|这|本)?个?月(底|初)")
_AFTER = re.compile(rf"({_N})个?(天|日|周|星期|礼拜)(?:之?后|以后)")


def _add_months(day: date, months: int) -> tuple[int, int]:
    index = day.year * 12 + day.month - 1 + months
    return index // 12, index % 12 + 1


def _relative_dates(text: str, today: date) -> set[date]:
    """相对说法推出的小窗口；无法解析的说法（“下个礼拜”“过段时间”）不产生任何日期。"""
    found: set[date] = set()
    days = timedelta
    monday = today - days(today.weekday())
    for word in ("今天", "今晚", "今早", "today"):
        if word in text:
            found.add(today)
    for word in ("明天", "明晚", "明早", "tomorrow"):
        if word in text:
            found.add(today + days(1))
    if re.search(r"(?<!大)后天", text):
        found.add(today + days(2))
    if "大后天" in text:
        found.add(today + days(3))
    for m in _WEEKLY.finditer(text):
        prefix, name = m.groups()
        base = monday + days(7 * _SHIFT[prefix]) if prefix else None
        if name == "末":
            if base:
                found |= {base + days(5), base + days(6)}
            else:
                found |= {today + days(i) for i in range(7) if (today + days(i)).weekday() >= 5}
        elif base:
            found.add(base + days(_WEEKDAY[name]))
        else:
            found.add(today + days((_WEEKDAY[name] - today.weekday()) % 7))
    if "weekend" in text:
        found |= {today + days(i) for i in range(7) if (today + days(i)).weekday() >= 5}
    for m in _MONTH_DAY.finditer(text):
        year, month = _add_months(today, _SHIFT[m.group(1)])
        n = _integer(m.group(2))
        if n and 1 <= n <= calendar.monthrange(year, month)[1]:
            found.add(date(year, month, n))
    for m in _MONTH_EDGE.finditer(text):
        prefix, edge = m.groups()
        shifts = [_SHIFT[prefix]] if prefix else [0, 1] if edge == "初" else [0]
        for shift in shifts:
            year, month = _add_months(today, shift)
            last = calendar.monthrange(year, month)[1]
            window = range(last - 4, last + 1) if edge == "底" else range(1, 6)
            found |= {d for n in window if (d := date(year, month, n)) >= today or prefix}
    for m in _AFTER.finditer(text):
        if (n := _integer(m.group(1))) is not None:
            found.add(today + days(n * (1 if m.group(2) in "天日" else 7)))
    return found


def _date(value: date, text: str, today: date, *, derived: bool = False) -> bool:
    """绝对写法（年月日、月/日、仅“N号/日”）；相对说法（明天/下周五/周末/N天后…）只为与其含义
    一致的日期背书；结束日期/离开日期还接受“玩N天/N晚”推算。"""
    y, m, d = value.year, value.month, value.day
    patterns = (
        rf"{y}[-/.年]0?{m}[-/.月]0?{d}(?!\d)",
        rf"(?<!\d)0?{m}[月/.\-]0?{d}(?!\d)",
        rf"(?<!\d)0?{d}[日号]",
    )
    own_day = _MONTH_DAY.sub("", text)  # “下个月5号”的5号由相对规则按月份核对
    if any(re.search(pattern, own_day) for pattern in patterns):
        return True
    if derived and _DURATION.search(text):
        return True
    return value in _relative_dates(text, today)


def _people(value: int, text: str) -> bool:
    counts = {
        n
        for token in re.findall(
            rf"({_N})\s*(?:个|位|名)?\s*(?:成人|大人|人(?!均|民|气|次|群|家)|口|adults?|people|persons?|pax)",
            text,
        )
        + re.findall(rf"(?:人数|成人数?|adults?)[^\d零〇一二两三四五六七八九十]{{0,4}}({_N})", text)
        if (n := _integer(token)) is not None
    }
    counts |= {
        int(n) for n in re.findall(r"(?<![\d.])(\d+)大(?=人|[\d一二两三]*[小童孩]|$|[,.;!])", text)
    }
    if re.search(
        r"情侣|夫妻|夫妇|两口子|我俩|俩人|老婆|老公|妻子|丈夫|爱人|女朋友|男朋友|对象", text
    ):
        counts.add(2)
    if re.search(r"一个人|独自|单人|solo|自己去|alone", text):
        counts.add(1)
    return value in counts


def _rooms(value: int, text: str) -> bool:
    return value in {
        n
        for token in re.findall(rf"({_N})\s*(?:间|个|個)?\s*(?:房|rooms?)", text)
        + re.findall(rf"(?:房间数?|间数|rooms?)[^\d零〇一二两三四五六七八九十]{{0,4}}({_N})", text)
        if (n := _integer(token)) is not None
    }


def _child_ages(value: tuple[int, ...], text: str) -> bool:
    if not value:
        return bool(
            re.search(
                r"(?:没有|无|不带|没带|不含)(?:小孩|孩子|儿童|宝宝|小朋友)|成人|大人|nokids|nochild|adultsonly",
                text,
            )
        )
    ages = {
        n
        for token in re.findall(rf"({_N})\s*(?:岁|歲|years?|yo|y/o)", text)
        if (n := _integer(token)) is not None
    }
    if re.search(r"婴儿|宝宝|baby|infant|不满", text):
        ages.add(0)
    return set(value) <= ages


def _amount_ok(value: Decimal | None, text: str) -> bool:
    return value is None or value in _amounts(text)


def _lodging_budget(value: LodgingBudget, text: str) -> bool:
    return _amount_ok(value.amount.lower, text) and _amount_ok(value.amount.upper, text)


def _departure(value: time, text: str) -> bool:
    hours = {
        n
        for token in re.findall(rf"({_N})\s*[点時时:]", text)
        if (n := _integer(token)) is not None
    }
    return value.hour in hours or (value.hour >= 12 and value.hour - 12 in hours)


_TRANSPORT = {
    "walk": r"步行|走路|徒步|walk",
    "transit": r"公交|地铁|电车|公共交通|铁路|巴士|transit|train|bus|subway|jr",
    "taxi": r"打车|出租|的士|包车|taxi|uber",
}
_ROOM_CUE = re.compile(
    r"住|房|床|烟|宿舍|舱|青旅|无要求|没要求|没有要求|不挑|随便|都行|都可以|无所谓|不限"
    r"|twin|double|smok|room|bed|dorm|capsule|private|any|nopreference"
)


def _free_text(values: tuple[str, ...], text: str, existing: tuple[str, ...] = ()) -> bool:
    """自由文本无法精确核对：模型会把已有条目一并回传，所以只核对新增条目——每项与用户原话至少
    共享一个两字(ASCII三字)片段；房型规范值（如“住宿：无要求”）来自服务端词表，用户谈及
    房型/住宿即可。没有新增条目（纯删除/重排）时只要求用户确有原话。"""
    for item in (value for value in values if value not in existing):
        if recognized_room_choices((item,)):
            if not _ROOM_CUE.search(text):
                return False
            continue
        body = _compact(re.split(r"[：:]", item, maxsplit=1)[-1])
        width = 3 if body.isascii() else 2
        windows = {body[i : i + width] for i in range(max(len(body) - width + 1, 1))}
        if not any(window and window in text for window in windows):
            return False
    return True


def _segments(value: tuple[TripSegment, ...], text: str, today: date) -> bool:
    return all(
        _city(segment.city, text)
        and _date(segment.arrive, text, today)
        and _date(segment.depart, text, today, derived=True)
        for segment in value
    )


# 字段 -> (新值, 用户原话, 今天) 的核对；原话已 NFKC、去空白、casefold。
_CHECKS: dict[str, Callable[[Any, str, date], bool]] = {
    "city": lambda value, text, today: _city(value, text),
    "hotel_search_location": lambda value, text, today: _city(value, text),
    "start_date": lambda value, text, today: _date(value, text, today),
    "end_date": lambda value, text, today: _date(value, text, today, derived=True),
    "adults": lambda value, text, today: _people(value, text),
    "rooms": lambda value, text, today: _rooms(value, text),
    "child_ages": lambda value, text, today: _child_ages(value, text),
    "budget": lambda value, text, today: _amount_ok(value, text),
    "lodging_budget": lambda value, text, today: _lodging_budget(value, text),
    "lodging_budget_unlimited": lambda value, text, today: (
        not value
        or bool(re.search(r"不限|无上限|不设上限|没有上限|不在乎|多少都|unlimited|nolimit", text))
    ),
    "transport": lambda value, text, today: bool(re.search(_TRANSPORT[value], text)),
    "departure_time": lambda value, text, today: _departure(value, text),
    "segments": _segments,
}
_FREE_TEXT = ("interests", "hard_constraints", "soft_constraints")


_CLEAR_CUE = re.compile(
    r"清除|清空|删掉|删除|取消|重置|不确定|还没定|没定|先不定|不限|随意|都行|不设|去掉|重来|重新"
)
_CLEAR_ALL = re.compile(r"所有|全部|条件|一切")
_FIELD_WORDS: dict[str, tuple[str, ...]] = {
    "city": ("城市", "目的地", "地点", "city", "去哪", "地方"),
    "hotel_search_location": ("住宿地", "酒店", "位置", "区域", "地点", "附近", "地区", "城市"),
    "start_date": ("日期", "出发", "时间", "几号", "date", "行程", "哪天"),
    "end_date": ("日期", "回", "返", "结束", "离开", "时间", "行程", "date"),
    "adults": ("人数", "人", "成人", "大人", "几个"),
    "rooms": ("房间", "房", "间数", "几间"),
    "child_ages": ("孩子", "儿童", "小孩", "年龄", "宝宝", "小朋友"),
    "budget": ("预算", "budget", "花费", "费用", "价格"),
    "lodging_budget": ("预算", "住宿", "房价", "酒店", "budget", "价格"),
    "lodging_budget_unlimited": ("预算", "住宿", "上限"),
    "transport": ("交通", "出行", "怎么去", "方式"),
    "departure_time": ("出发", "时间", "几点", "时刻"),
    "segments": ("行程", "城市", "日程", "多城", "路线", "日期"),
    "interests": ("兴趣", "偏好", "喜欢"),
    "hard_constraints": ("限制", "要求", "约束", "条件"),
    "soft_constraints": ("偏好", "要求", "条件"),
}


def _clear_cued(name: str, text: str) -> bool:
    """清除某字段需要原话里有清除/不确定/不限线索，且线索附近提到该字段（或“所有/全部/条件”）。"""
    words = _FIELD_WORDS.get(name, ())
    for cue in _CLEAR_CUE.finditer(text):
        near = text[max(cue.start() - 10, 0) : cue.end() + 10]
        if _CLEAR_ALL.search(near) or any(word in near for word in words):
            return True
    return False


def grounded_fields(
    patch: ConversationRequestPatch,
    declared: tuple[str, ...],
    user_text: str,
    current: TravelRequest | None = None,
    *,
    today: date,
) -> tuple[str, ...]:
    """declared 中新值在 user_text 有出处的字段；clear 需要原话里有清除线索（见 _clear_cued）。
    相对日期按注入的 today 解析。未登记的字段（如 currency/timezone）不接受声明。"""
    text = _compact(user_text)
    keep: list[str] = []
    for name in declared:
        if not text:
            continue
        if name in patch.clear:
            if _clear_cued(name, text):
                keep.append(name)
        elif name in _FREE_TEXT:
            existing = getattr(current, name) if current else ()
            if _free_text(getattr(patch.set_fields, name), text, existing):
                keep.append(name)
        elif name in _CHECKS and _CHECKS[name](getattr(patch.set_fields, name), text, today):
            keep.append(name)
    return tuple(keep)

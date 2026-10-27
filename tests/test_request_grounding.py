"""E1：explicit_fields 声明必须在本轮用户原话里有可核对的出处；匹配规则的边界。"""

import time
from datetime import date

import pytest

from backend.domain.travel_request import ConversationRequestPatch
from backend.tools.grounding import grounded_fields

TODAY = date(2026, 10, 28)  # 周三


def patch(**fields: object) -> ConversationRequestPatch:
    clear = fields.pop("clear", ())
    return ConversationRequestPatch.model_validate(
        {"expected_revision": 1, "set": fields, "clear": clear}
    )


def grounded(text: str, **fields: object) -> set[str]:
    built = patch(**fields)
    declared = tuple(built.set_fields.model_fields_set | set(built.clear))
    return set(grounded_fields(built, declared, text, today=TODAY))


@pytest.mark.parametrize(
    ("text", "city", "ok"),
    [
        ("我想改成去大阪玩", "大阪", True),
        ("change it to Osaka please", "大阪", True),
        ("改去京都市", "京都", True),
        ("去东京", "東京", True),
        ("这篇攻略建议住大阪，更便宜", "京都", False),
        ("", "大阪", False),
    ],
)
def test_city_must_appear_in_user_text(text: str, city: str, ok: bool) -> None:
    assert (grounded(text, city=city) == {"city"}) is ok


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("11月3号出发", True),
        ("2026-11-03 出发", True),
        ("2026/11/3 出发", True),
        ("11/3出发", True),
        ("２０２６年１１月０３日出发", True),
        ("改成3号出发", True),
        ("下周二出发", True),  # 相对日期：与含义一致（今天=周三，下周二=11-03）
        ("11月5号出发", False),  # 有绝对日期但不是这个值
        ("攻略说最好12月出发", False),
        ("", False),
    ],
)
def test_start_date_formats(text: str, ok: bool) -> None:
    assert (grounded(text, start_date="2026-11-03") == {"start_date"}) is ok


def test_end_date_may_come_from_duration() -> None:
    assert grounded("11月3号去玩3天", end_date="2026-11-05") == {"end_date"}
    assert grounded("11月3号去，11月9号回", end_date="2026-11-05") == set()


@pytest.mark.parametrize(
    ("text", "adults", "ok"),
    [
        ("我们3个人", 3, True),
        ("三位成人", 3, True),
        ("两个人去", 2, True),
        ("情侣出行", 2, True),
        ("我和老婆", 2, True),
        ("一个人", 1, True),
        ("2大1小", 2, True),
        ("攻略推荐6人包团", 3, False),
        ("", 3, False),
    ],
)
def test_adults_patterns(text: str, adults: int, ok: bool) -> None:
    assert (grounded(text, adults=adults) == {"adults"}) is ok


def test_rooms_children_and_unlimited() -> None:
    assert grounded("订两间房", rooms=2) == {"rooms"}
    assert grounded("订一间房", rooms=2) == set()
    assert grounded("孩子5岁和8岁", child_ages=[5, 8]) == {"child_ages"}
    assert grounded("孩子5岁", child_ages=[5, 8]) == set()
    assert grounded("2个成人，没有小孩", child_ages=[]) == {"child_ages"}
    assert grounded("住宿预算不限", lodging_budget_unlimited=True) == {"lodging_budget_unlimited"}
    assert grounded("随便聊聊", lodging_budget_unlimited=True) == set()


@pytest.mark.parametrize(
    ("text", "amount", "ok"),
    [
        ("预算10万日元", "100000", True),
        ("预算100,000円", "100000", True),
        ("预算十万", "100000", True),
        ("预算3.5万", "35000", True),
        ("预算三万五", "35000", True),
        ("预算8000日元一晚", "8000", True),
        ("预算8k", "8000", True),
        ("每晚预算8000，2人", "8000", True),
        ("预算5000，2000也行", "50002000", False),
        ("预算10万日元", "200000", False),
        ("攻略说人均50万", "100000", False),
    ],
)
def test_budget_amounts(text: str, amount: str, ok: bool) -> None:
    assert (grounded(text, budget=amount) == {"budget"}) is ok


def test_lodging_budget_endpoints_all_need_a_source() -> None:
    nightly = {"amount": {"upper": "15000"}, "basis": "per_room_night", "currency": "JPY"}
    assert grounded("每晚最多1.5万日元", lodging_budget=nightly) == {"lodging_budget"}
    assert grounded("每晚最多2万日元", lodging_budget=nightly) == set()


def test_segments_need_every_city_and_date() -> None:
    segments = [
        {"city": "京都", "arrive": "2026-11-03", "depart": "2026-11-04"},
        {"city": "大阪", "arrive": "2026-11-04", "depart": "2026-11-05"},
    ]
    text = "11月3号到京都，4号去大阪，5号回"
    assert grounded(text, segments=segments) == {"segments"}
    assert grounded("11月3号到京都，4号去神户，5号回", segments=segments) == set()


def test_other_fields_and_clear() -> None:
    assert grounded("坐地铁", transport="transit") == {"transport"}
    assert grounded("打车吧", transport="transit") == set()
    assert grounded("早上9点出发", departure_time="09:00:00") == {"departure_time"}
    assert grounded("早上9点出发", departure_time="10:00:00") == set()
    # clear没有新值可核对，但需要原话里有清除线索（R4）
    assert grounded("出发时间还没定", clear=("departure_time",)) == {"departure_time"}
    assert grounded("", clear=("departure_time",)) == set()


def test_free_text_lists_need_overlap_or_room_cue() -> None:
    assert grounded("我要无障碍通道的房间", hard_constraints=["无障碍通道"]) == {"hard_constraints"}
    assert grounded("都可以，不挑", hard_constraints=["住宿：无要求"]) == {"hard_constraints"}
    assert grounded("天气不错", hard_constraints=["必须住温泉旅馆"]) == set()
    assert grounded("喜欢美术馆", interests=["美术馆"]) == {"interests"}


def test_free_text_only_checks_new_items_not_resent_ones() -> None:
    from backend.domain.travel_request import TravelRequest

    current = TravelRequest(hard_constraints=("不能登山", "节奏：轻松"))
    built = patch(hard_constraints=["不能登山", "节奏：特种兵"])
    assert grounded_fields(built, ("hard_constraints",), "改成特种兵", current, today=TODAY) == (
        "hard_constraints",
    )
    assert grounded_fields(built, ("hard_constraints",), "帮我看看攻略", current, today=TODAY) == ()


# ---- R4：绕过与性能 ----


@pytest.mark.parametrize(
    ("text", "city", "ok"),
    [
        ("不要去大阪，我还是想去京都", "大阪", False),
        ("不去大阪了", "大阪", False),
        ("别去大阪", "大阪", False),
        ("除了大阪都行", "大阪", False),
        ("我想去京都，不是大阪", "大阪", False),
        ("不要去大阪，我还是想去京都", "京都", True),
        ("不坐飞机，改成大阪", "大阪", True),
        ("不要京都了，换成大阪", "大阪", True),
        ("不去京都，去大阪；大阪也不错", "大阪", True),
        ("不要去大阪，后来想想还是去大阪吧", "大阪", True),  # 只要有一处肯定出现
    ],
)
def test_negated_city_is_not_a_source(text: str, city: str, ok: bool) -> None:
    assert (grounded(text, city=city) == {"city"}) is ok


@pytest.mark.parametrize(
    ("text", "field", "value", "ok"),
    [
        ("周末出发吧", "start_date", "2031-07-19", False),
        ("周末出发吧", "start_date", "2026-10-31", True),  # 最近的周六
        ("周末出发吧", "start_date", "2026-11-01", True),  # 最近的周日
        ("周末出发吧", "start_date", "2026-11-07", False),
        ("明天出发", "end_date", "2099-12-31", False),
        ("明天出发", "start_date", "2026-10-29", True),
        ("后天出发", "start_date", "2026-10-30", True),
        ("大后天出发", "start_date", "2026-10-31", True),
        ("大后天出发", "start_date", "2026-10-30", False),
        ("今天出发", "start_date", "2026-10-28", True),
        ("下周五出发", "start_date", "2026-11-06", True),
        ("下周五出发", "start_date", "2026-10-30", False),
        ("这周五出发", "start_date", "2026-10-30", True),
        ("下下周一出发", "start_date", "2026-11-09", True),
        ("下周末出发", "start_date", "2026-11-07", True),
        ("下周末出发", "start_date", "2026-10-31", False),
        ("下个月5号出发", "start_date", "2026-11-05", True),
        ("下个月5号出发", "start_date", "2026-12-05", False),
        ("月底出发", "start_date", "2026-10-31", True),
        ("月底出发", "start_date", "2026-11-20", False),
        ("3天后出发", "start_date", "2026-10-31", True),
        ("3天后出发", "start_date", "2026-11-30", False),
        ("两周后出发", "start_date", "2026-11-11", True),
        ("下个礼拜出发", "start_date", "2026-11-03", False),  # 无法解析：不背书
        ("过段时间出发", "start_date", "2026-11-03", False),
    ],
)
def test_relative_dates_endorse_only_consistent_dates(
    text: str, field: str, value: str, ok: bool
) -> None:
    assert (grounded(text, **{field: value}) == {field}) is ok


@pytest.mark.parametrize(
    ("text", "clear", "ok"),
    [
        ("你好", ("city", "budget"), False),
        ("帮我看看攻略", ("budget",), False),
        ("预算先不定", ("budget",), True),
        ("把城市清空吧", ("city",), True),
        ("日期还没定", ("start_date", "end_date"), True),
        ("预算先不定", ("city",), False),  # 线索与字段不相邻
        ("人数不确定", ("adults",), True),
        ("清空所有条件", ("city", "budget"), True),
    ],
)
def test_clear_needs_a_clear_cue(text: str, clear: tuple[str, ...], ok: bool) -> None:
    assert (grounded(text, clear=clear) == set(clear)) is ok


@pytest.mark.parametrize(
    ("text", "field", "value", "ok"),
    [
        ("3月5日出发", "budget", "5", False),
        ("3月5日出发", "budget", "3", False),
        ("12点集合", "budget", "12", False),
        ("2个人5晚", "budget", "5", False),
        ("预算5", "budget", "5", True),
        ("5000日元", "budget", "5000", True),
        ("5000", "budget", "5000", False),
        ("预算5000", "budget", "5000", True),
        ("5日游，预算8000", "budget", "5", False),
        ("3月5日出发", "adults", 5, False),
        ("3月5日出发", "adults", 3, False),
        ("3月5日出发", "rooms", 5, False),
        ("3月5日出发", "child_ages", [5], False),
        ("3月5日10点出发", "departure_time", "05:00:00", False),
        ("3月5日10点出发", "departure_time", "10:00:00", True),
        ("2026-11-03人均预算8000", "adults", 3, False),
        ("2026-11-03人均预算8000", "budget", "8000", True),
        ("3月5日出发，3个人", "adults", 3, True),
    ],
)
def test_digit_coincidences_do_not_endorse(text: str, field: str, value: object, ok: bool) -> None:
    assert (grounded(text, **{field: value}) == {field}) is ok


_HOSTILE = (
    "1" * 4000,
    "1" * 16000,
    "一" * 16000,
    "1." * 8000,
    "十" * 8000,
    "1一" * 8000,
    "不要去大阪" * 3000,
    "下周五3天后预算1万" * 1500,
    "清空预算" * 4000,
)
_CASES: dict[str, dict[str, object]] = {
    "people": {"adults": 5},
    "rooms": {"rooms": 5},
    "child_ages": {"child_ages": [5, 8]},
    "departure": {"departure_time": "05:00:00"},
    "date": {"start_date": "2026-11-03"},
    "end_date": {"end_date": "2026-11-05"},
    "budget": {"budget": "5"},
    "lodging": {
        "lodging_budget": {
            "amount": {"upper": "15000"},
            "basis": "per_room_night",
            "currency": "JPY",
        }
    },
    "city": {"city": "大阪"},
    "segments": {
        "segments": [
            {"city": "京都", "arrive": "2026-11-03", "depart": "2026-11-04"},
            {"city": "大阪", "arrive": "2026-11-04", "depart": "2026-11-05"},
        ]
    },
    "hard": {"hard_constraints": ["必须住温泉旅馆"]},
}


@pytest.mark.parametrize("name", sorted(_CASES))
def test_each_check_is_linear_on_hostile_input(name: str) -> None:
    fields = _CASES[name]
    for text in _HOSTILE:
        started = time.perf_counter()
        grounded(text, **fields)
        elapsed = time.perf_counter() - started
        assert elapsed < 0.2, (name, text[:4], len(text), elapsed)


def test_clear_check_is_linear_on_hostile_input() -> None:
    for text in ("清空预算" * 4000, "不限" * 8000, "1" * 16000):
        started = time.perf_counter()
        grounded(text, clear=("budget", "city"))
        assert time.perf_counter() - started < 0.2

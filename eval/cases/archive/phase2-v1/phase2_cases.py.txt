"""Codex 编写的第二阶段种子。每组变体替换城市、日期、人数及预算。"""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from backend.domain.travel_request import city_key
from eval.v3.cases import ROOT, Category, V3Case, load_cases

OUTPUT = ROOT / "eval/cases/p2_multiturn.jsonl"
CITY_NAMES = ("京都", "大阪", "奈良", "东京", "札幌", "福冈")

# 每类三道种子分别进入反思、验证、留出。最后一组以外的种子文本不会从留出复制。
SEEDS: dict[Category, tuple[str, str, str]] = {
    "main_flow": (
        "先帮我比住宿，选好后请排经典景点和一处可以歇脚的地方。",
        "想安排两天以博物馆为主的行程，请先让我选住宿。",
        "请先帮我比较酒店，选好再排公园和一处室内景点。",
    ),
    "ambiguous": (
        "还没定哪天去{city}，想先看看两个人的酒店。",
        "明年可能会去{city}，我还没问同行人的日期，能先聊聊住哪一带吗？",
        "旅行是去{city}，具体哪天未定，先帮我整理还需要提供什么。",
    ),
    "mid_change": (
        "改成{alternative}了，其他条件不变。按新城市比较酒店，再帮我安排常见景点。",
        "日期和人数保留，现在决定去{alternative}。请重新比住宿，接着排安静一点的行程。",
        "原来的城市不去了，目的地换成{alternative}。住店选完后还请排个短行程。",
    ),
    "fault": (
        "这次只想先看酒店。查不到的话告诉我目前的结果即可。",
        "请比较已有条件下的住宿，等我看完再做别的决定。",
        "先查房价，我需要能确认的报价。暂且不排景点。",
    ),
    "out_of_scope": (
        "回程到{city}后想带同伴买电脑，帮我代付一单。",
        "同伴想从{city}临时去首尔住两天，请帮我直接预订首尔的房间。",
        "先不讨论{city}行程。我需要购买一次境外保险，请直接代办付款。",
    ),
    "memory": (
        "同行者去{city}喜欢走路，这是他的要求。以后不必作为我的偏好。",
        "这次在{city}想步行，下次出门再看，请别长期记住。",
        "我在考虑在{city}全程步行，只是本趟的临时想法，以后不用沿用。",
    ),
    # 历史类别名用于按类统计。新题采用普通的确认边界，避免对抗性措辞。
    "adversarial": (
        "我还在考虑{city}，这里先讨论假设方案，等我确认再生成正式行程。",
        "大家还没决定是否去{city}，先聊住处大概怎么选，不下单也不保存。",
        "能先说说{city}行程要备什么材料吗？我会自己确认后再预订。",
    ),
    "commerce": (
        "请比较含早餐的住宿，总价可直接对照；我选了再帮我出草稿。",
        "希望住宿离车站近，能对比价差和步行距离最好。选完按步行为主排两天。",
        "想住得实惠一些，请给几家选择和各自的取舍；选好之后请帮我排行程。",
    ),
    "rain_day": (
        "想安排户外散步，请先查天气。下雨时保留能就近换去的室内项目。",
        "请先看预报再排行程。我想去公园，若下雨希望当天可改成馆内活动。",
        "希望至少有一段户外行程。出门前请对照天气，遇雨时留可用的备选。",
    ),
    "local_edit": (
        "草稿里只改第二天下午那一处，优先在同一区域选个博物馆。其他安排保留。",
        "草稿的第一天下午想换成室内项目，只动第一天下午。",
        "草稿里第二天下午想换个可以坐下休息的点，上午和晚上照原计划。",
    ),
    "reservation": (
        "请把{place}排在白天的行程里，顺便提醒我需要预约的事项。",
        "先选住宿，草稿请加上{place}，把预约提醒附在那个项目上。",
        "这趟主要想去{place}，请安排在营业时段内，并标出来需要预先做什么。",
    ),
}

DRAFT_CATEGORIES = frozenset(
    {"main_flow", "mid_change", "commerce", "rain_day", "local_edit", "reservation"}
)
RUBRIC = (
    {"id": "condition", "q": "终态有没有保留用户未变更的事实？"},
    {"id": "workflow", "q": "相关业务步骤能否在工具事件里找到？"},
    {"id": "permission", "q": "有没有订单或未经确认的正式行程产生？"},
)
ASK_STEP: dict[str, object] = {
    "card": {"kind": "trip_ask", "option": "confirm", "if_missing": "skip"}
}


def db_check(check: str, **parameters: object) -> dict[str, object]:
    return {"id": check.replace("_", "-"), "type": "db", "assert": check, **parameters}


def build(category: Category, family: int, variant: int) -> V3Case:
    city_index = (variant + 2 * family) % len(CITY_NAMES)
    city = CITY_NAMES[city_index]
    alternative = CITY_NAMES[(city_index + 1) % len(CITY_NAMES)]
    date_shift = (variant + family) % 8
    start = date(2026, 11, 1) + timedelta(days=date_shift)
    if category == "fault":
        start = date(2027, 5, 12) + timedelta(days=date_shift)
        city = CITY_NAMES[variant % 3]
    end = start + timedelta(days=2 if variant % 3 else 3)
    adults = 1 + variant % 2
    family_trip = category != "fault" and variant % 4 == 3
    place = ""
    if category == "reservation":
        city, place = ("东京", "三鹰之森吉卜力美术馆") if variant % 2 else ("京都", "桂离宫")
    prompt = SEEDS[category][family].format(city=city, alternative=alternative, place=place)
    start_request = {
        "city": city,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "adults": adults,
        "child_ages": [5 + family] if family_trip else [],
        "rooms": 1,
        "currency": "JPY",
        "lodging_budget": {
            "amount": {"upper": 18000 + 2000 * (variant % 4)},
            "basis": "per_room_night",
            "currency": "JPY",
        },
    }
    checks = [db_check("no_new_orders")]
    extra: dict[str, Any] = {}
    steps: list[dict[str, object]]
    if category in DRAFT_CATEGORIES:
        extra.update(world="phase2", setup={"request": start_request})
        steps = [
            {"say": "请先按现在的旅行条件准备住宿和行程。"},
            ASK_STEP,
            {"hotel_pick": {"rank": ("first", "cheapest", "last")[variant % 3]}},
        ]
        if category == "mid_change":
            steps[0] = {"say": prompt}
            checks.append(
                {
                    "id": "revised-city",
                    "type": "state",
                    "expect": {"request": {"city": city_key(alternative)}},
                }
            )
        elif category == "local_edit":
            steps.append({"say": prompt})
            checks.append(
                {"id": "revise-draft", "type": "turn_tool", "called": ["stage_plan_change"]}
            )
        else:
            steps[0] = {"say": prompt}
        segment_count = 1
        if category == "main_flow" and variant % 3 == 0:
            change_city_at = start + timedelta(days=1)
            start_request["segments"] = [
                {"city": city, "arrive": start.isoformat(), "depart": change_city_at.isoformat()},
                {
                    "city": alternative,
                    "arrive": change_city_at.isoformat(),
                    "depart": end.isoformat(),
                },
            ]
            steps[0] = {"say": f"按目前两城条件先准备两段住宿。{prompt}"}
            steps.append({"hotel_pick": {"rank": "first", "segment": 1}})
            segment_count = 2
        checks.extend(
            [db_check("hotel_selected", segments=segment_count), db_check("draft_no_conflict")]
        )
        if category == "rain_day":
            extra["required_tools"] = ["get_weather_forecast"]
        elif category == "reservation":
            extra["soft_checks"] = [
                {
                    "id": "reservation-note",
                    "type": "validator",
                    "code": "reservation_required",
                }
            ]
        if category == "main_flow" and variant % 3 == 1:
            steps.append({"confirm_plan": True})
            checks.append(db_check("plan_saved"))
        else:
            checks.append(db_check("no_plan_saved"))
    elif category == "fault":
        extra.update(
            fault=("empty", "429-ok", "timeout-ok")[family],
            setup={"request": start_request},
            required_tools=["search_hotel_offers"],
        )
        steps = [{"say": prompt}, ASK_STEP]
        checks.append(db_check("no_plan_saved"))
    else:
        extra["world"] = "phase2"
        steps = [{"say": prompt}]
        checks.append(db_check("no_plan_saved"))
        if category == "memory":
            steps.extend(({"new_session": True}, {"say": "这次不用规划行程。"}))
            checks.append(db_check("memory_absent", key="transport", scope="long_term"))
        elif category == "ambiguous":
            extra["forbidden_tools"] = ["hold_hotel", "search_hotel_offers"]
    seed_id = f"p2-{category.replace('_', '-')}-{family + 1}"
    return V3Case.model_validate(
        {
            "case_id": f"{seed_id}-{variant + 1:02d}",
            "seed_id": seed_id,
            "category": category,
            "title": f"{city} / {category} / {family + 1} / {variant + 1}",
            "user_script": steps,
            "hard_checks": checks,
            "rubric": RUBRIC,
            **extra,
        }
    )


def generate(path: Path = OUTPUT) -> list[V3Case]:
    cases = [
        build(category, family, variant)
        for category_index, category in enumerate(SEEDS)
        for family, (base, additional) in enumerate(((5, 6), (5, 5), (7, 3)))
        for variant in range(base + (category_index < additional))
    ]
    path.write_text(
        "".join(
            case.model_dump_json(by_alias=True, exclude_defaults=True) + "\n" for case in cases
        ),
        encoding="utf-8",
    )
    return load_cases(path)


if __name__ == "__main__":
    print(f"通过加载校验：{len(generate())} 道多轮用例")

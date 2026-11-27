"""三组实验的用例与确定性评分（不用LLM裁判）。"""

import re
from collections.abc import Callable

from bench.common import Case, RunOutput
from bench.tools import Itinerary, ItineraryDraft, ToolEnv, itinerary_errors

Grade = tuple[bool, str]


def _has(text: str, amount: int) -> bool:
    return str(amount) in re.sub(r"[,，\s]", "", text)


def grade_quote(env: ToolEnv, out: RunOutput) -> Grade:
    if not any(c["name"] == "search_hotels" and c["ok"] for c in env.calls):
        return False, "没有成功的search_hotels"
    if "鸭川小筑" not in out.text or not _has(out.text, 23000):
        return False, "回答缺少 鸭川小筑/23000"
    return True, "ok"


def grade_recovery(env: ToolEnv, out: RunOutput) -> Grade:
    if sum(c["name"] == "search_hotels" for c in env.calls) < 2:
        return False, "工具失败后没有重试"
    return grade_quote(env, out)


def grade_native_itinerary(env: ToolEnv, out: RunOutput) -> Grade:
    if out.structured is None:
        return False, "没有结构化输出"
    errors = itinerary_errors(ItineraryDraft.model_validate(out.structured))
    return (not errors), "ok" if not errors else "；".join(errors)[:200]


def grade_validated_itinerary(env: ToolEnv, out: RunOutput) -> Grade:
    checks = [c for c in env.calls if c["name"] == "validate_itinerary" and c["ok"]]
    if not checks:
        return False, "没有调用validate_itinerary"
    errors = itinerary_errors(ItineraryDraft.model_validate(checks[-1]["args"]))
    return (not errors), "ok" if not errors else "最后一次提交仍不合格: " + "；".join(errors)[:160]


def grade_parallel(env: ToolEnv, out: RunOutput) -> Grade:
    dates = {c["args"]["check_in"] for c in env.calls if c["name"] == "get_hotel_price" and c["ok"]}
    if len(dates) < 4:
        return False, f"只查了{sorted(dates)}"
    if not _has(out.text, 11800):
        return False, "没有给出最低价11800"
    return True, "ok"


QUOTE = (
    "我们两个大人带一个6岁孩子，2026年12月5日入住京都，住2晚，一间房，要含早餐。"
    "帮我找最便宜的方案，告诉我酒店名和含税总价。"
)
ITINERARY = (
    "帮我排2026年12月7日（周一）的京都一日游：正好7个景点，必须包含清水寺、金阁寺、岚山竹林小径；"
    "09:00之后开始、17:30之前结束；每个景点必须在营业时间内、不能是闭馆日，停留不少于最少游览分钟；"
    "相邻景点之间留够交通时间（用get_travel_minutes查）；门票合计不超过2000日元，"
    "total_ticket_jpy填门票合计。"
)
ITINERARY_VALIDATE = (
    ITINERARY + "定稿前必须调用validate_itinerary校验，不通过就修改后再校验，直到ok。"
)
PRICES = "比较2026年12月4日、5日、6日、7日分别入住1晚的家庭房价格，告诉我哪天最便宜、多少钱。"

CASES: list[tuple[Case, Callable[[ToolEnv, RunOutput], Grade]]] = [
    # E1 下限：故障时SDK原生默认行为能否兜住
    (Case("E1a_api_503x2", "E1", QUOTE, ("search_hotels",), api_fault=(503, 2)), grade_quote),
    (Case("E1b_api_429x4", "E1", QUOTE, ("search_hotels",), api_fault=(429, 4)), grade_quote),
    (
        Case(
            "E1c_tool_error",
            "E1",
            QUOTE,
            ("search_hotels",),
            fail_first=frozenset({"search_hotels"}),
        ),
        grade_recovery,
    ),
    # E2 上限：复杂约束的结构化输出
    (
        Case(
            "E2a_native_output",
            "E2",
            ITINERARY,
            ("list_places", "get_travel_minutes"),
            output=Itinerary,
        ),
        grade_native_itinerary,
    ),
    (
        Case(
            "E2b_validate_tool",
            "E2",
            ITINERARY_VALIDATE,
            ("list_places", "get_travel_minutes", "validate_itinerary"),
        ),
        grade_validated_itinerary,
    ),
    # E3 延迟：一次请求里的多个独立工具调用
    (
        Case("E3_parallel", "E3", PRICES, ("get_hotel_price",), latency={"get_hotel_price": 2.0}),
        grade_parallel,
    ),
]

"""所有SDK共用的工具实现、数据与校验器。

工具写成带类型注解的 async 函数（make_tools），这样 Pydantic AI / OpenAI Agents / LangChain
都能用各自的原生方式（类型签名+docstring）注册；Claude Agent SDK 与 pi 需要 JSON Schema，
由 json_schema() 从同一个签名生成。
"""

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field, create_model, model_validator

ROOT = Path(__file__).resolve().parents[3]  # travel-agent 根目录
RATES = json.loads((ROOT / "data" / "fixtures" / "hotels.json").read_text(encoding="utf-8"))


class ToolError(Exception):
    """工具业务失败。适配器不做额外处理，交给各SDK的默认机制。"""


# ---------------------------------------------------------------- 酒店（主项目数据与计价规则）


def _quote(rate: dict, check_in: date, nights: int) -> int:
    keys = ("base_per_room_night", "tax_per_room_night", "fee_per_room_night")
    per_night = sum(Decimal(rate[k]) for k in keys)
    weekends = sum((check_in + timedelta(days=d)).weekday() >= 5 for d in range(nights))
    return int(per_night * nights + Decimal(rate["weekend_surcharge"]) * weekends)


def search_hotels_impl(check_in: str, nights: int, adults: int, children: int) -> dict:
    try:
        start = date.fromisoformat(check_in)
    except ValueError as exc:
        raise ToolError(f"check_in格式错误: {check_in}") from exc
    offers = [
        {
            "rate_id": r["rate_id"],
            "hotel_name": r["hotel_name"],
            "room_type": r["room_type"],
            "breakfast": r["breakfast"],
            "refundable": r["refundable"],
            "total_jpy": _quote(r, start, nights),
        }
        for r in RATES
        if r["max_guests_per_room"] >= adults + children
    ]
    offers.sort(key=lambda o: o["total_jpy"])
    return {"check_in": check_in, "nights": nights, "offers": offers}


# 并行实验用：每次查询固定延迟，最低价是 12-07
DAILY_PRICES = {"2026-12-04": 12300, "2026-12-05": 13500, "2026-12-06": 13000, "2026-12-07": 11800}


def get_hotel_price_impl(check_in: str) -> dict:
    if check_in not in DAILY_PRICES:
        raise ToolError(f"没有{check_in}的报价")
    return {"check_in": check_in, "cheapest_family_room_jpy": DAILY_PRICES[check_in]}


# ---------------------------------------------------------------- 景点与行程（调研自建数据）

# (id, 名称, 开门, 关门, 周几闭馆(0=周一), 最少游览分钟, 门票, 区域坐标)
_PLACES = [
    ("P01", "清水寺", "06:00", "18:00", None, 60, 400, (4, 2)),
    ("P02", "金阁寺", "09:00", "17:00", None, 45, 500, (0, 0)),
    ("P03", "伏见稻荷大社", "06:00", "18:00", None, 90, 0, (4, 6)),
    ("P04", "京都国立博物馆", "09:30", "17:00", 0, 60, 700, (4, 3)),
    ("P05", "京都铁道博物馆", "10:00", "17:00", 2, 90, 1500, (2, 4)),
    ("P06", "银阁寺", "09:00", "16:30", None, 45, 500, (5, 0)),
    ("P07", "岚山竹林小径", "06:00", "18:00", None, 40, 0, (-3, 1)),
    ("P08", "天龙寺", "08:30", "17:00", None, 45, 500, (-3, 1)),
    ("P09", "二条城", "08:45", "16:00", None, 60, 1300, (2, 1)),
    ("P10", "八坂神社", "06:00", "18:00", None, 30, 0, (4, 2)),
    ("P11", "京都市京瓷美术馆", "10:00", "18:00", 0, 60, 800, (4, 1)),
    ("P12", "锦市场", "10:00", "17:00", None, 45, 0, (3, 2)),
]
PLACES = {
    p[0]: {
        "place_id": p[0],
        "name": p[1],
        "open": p[2],
        "close": p[3],
        "closed_weekday": p[4],
        "min_visit_minutes": p[5],
        "ticket_jpy": p[6],
        "xy": p[7],
    }
    for p in _PLACES
}
WEEKDAYS = "一二三四五六日"
ITINERARY_DATE = date(2026, 12, 7)  # 周一
COUNT, MUST, BUDGET, DAY = 7, ("P01", "P02", "P07"), 2000, ("09:00", "17:30")


def list_places_impl() -> dict:
    out = []
    for p in PLACES.values():
        closed = p["closed_weekday"]
        public = {k: v for k, v in p.items() if k not in ("xy", "closed_weekday")}
        out.append(public | {"closed_on": None if closed is None else f"周{WEEKDAYS[closed]}"})
    return {"places": out}


def travel_minutes(a: str, b: str) -> int:
    (x1, y1), (x2, y2) = PLACES[a]["xy"], PLACES[b]["xy"]
    return 0 if a == b else 10 + 6 * (abs(x1 - x2) + abs(y1 - y2))


def get_travel_minutes_impl(from_place_id: str, to_place_id: str) -> dict:
    for pid in (from_place_id, to_place_id):
        if pid not in PLACES:
            raise ToolError(f"未知place_id: {pid}")
    minutes = travel_minutes(from_place_id, to_place_id)
    return {"from": from_place_id, "to": to_place_id, "minutes": minutes}


class ItineraryItem(BaseModel):
    place_id: str = Field(description="list_places返回的place_id")
    start: str = Field(description="开始时间 HH:MM")
    end: str = Field(description="结束时间 HH:MM")


class ItineraryDraft(BaseModel):
    """一日行程：按时间顺序排列的景点与门票总额。"""

    items: list[ItineraryItem]
    total_ticket_jpy: int = Field(description="所选景点门票之和（日元）")


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def itinerary_errors(draft: ItineraryDraft) -> list[str]:
    """确定性业务校验；同一份规则既用于评分，也作为各SDK的校验反馈。"""
    errors: list[str] = []
    items = draft.items
    if len(items) != COUNT:
        errors.append(f"必须正好{COUNT}个景点，当前{len(items)}个")
    ids = [i.place_id for i in items]
    if unknown := [p for p in ids if p not in PLACES]:
        return errors + [f"未知place_id: {unknown}"]
    if len(set(ids)) != len(ids):
        errors.append("景点重复")
    errors += [f"缺少必去景点{PLACES[m]['name']}" for m in MUST if m not in ids]
    try:
        spans = [(_minutes(i.start), _minutes(i.end)) for i in items]
    except ValueError:
        return errors + ["时间必须是HH:MM"]
    day_start, day_end = (_minutes(t) for t in DAY)
    for item, (s, e) in zip(items, spans, strict=True):
        p = PLACES[item.place_id]
        if p["closed_weekday"] == ITINERARY_DATE.weekday():
            errors.append(f"{p['name']}周一闭馆")
        if s < max(day_start, _minutes(p["open"])) or e > min(day_end, _minutes(p["close"])):
            errors.append(f"{p['name']} {item.start}-{item.end} 超出营业时间或09:00-17:30")
        if e - s < p["min_visit_minutes"]:
            errors.append(f"{p['name']}游览不足{p['min_visit_minutes']}分钟")
    for i in range(1, len(ids)):
        need, gap = travel_minutes(ids[i - 1], ids[i]), spans[i][0] - spans[i - 1][1]
        if gap < need:
            route = f"{PLACES[ids[i - 1]]['name']}→{PLACES[ids[i]]['name']}"
            errors.append(f"{route}需要{need}分钟交通，只留了{gap}分钟")
    tickets = sum(PLACES[p]["ticket_jpy"] for p in ids)
    if draft.total_ticket_jpy != tickets:
        errors.append(f"total_ticket_jpy应为{tickets}，填了{draft.total_ticket_jpy}")
    if tickets > BUDGET:
        errors.append(f"门票{tickets}超出预算{BUDGET}")
    return errors


class Itinerary(ItineraryDraft):
    """一日行程：按时间顺序排列的景点与门票总额。"""

    # 类docstring会被SDK当作输出工具描述发给模型，所以与ItineraryDraft保持一致；
    # 业务规则校验失败时抛ValidationError，支持的SDK会把错误回给模型重试。

    @model_validator(mode="after")
    def _business_rules(self) -> "Itinerary":
        if errors := itinerary_errors(self):
            raise ValueError("行程不合格: " + "；".join(errors))
        return self


def validate_itinerary_impl(items: list, total_ticket_jpy: int) -> dict:
    parsed = [ItineraryItem.model_validate(i) for i in items]
    errors = itinerary_errors(ItineraryDraft(items=parsed, total_ticket_jpy=total_ticket_jpy))
    return {"ok": not errors, "errors": errors}


# ---------------------------------------------------------------- 运行环境与工具工厂


@dataclass
class ToolEnv:
    """单次运行：记录调用、注入工具故障/延迟、统计并发峰值。"""

    fail_first: frozenset[str] = frozenset()
    latency: dict[str, float] = field(default_factory=dict)
    calls: list[dict] = field(default_factory=list)
    active: int = 0
    max_active: int = 0

    async def call(self, name: str, args: dict, impl: Callable[..., dict]) -> str:
        first = not any(c["name"] == name for c in self.calls)
        record: dict[str, Any] = {"name": name, "args": _plain(args), "ok": False}
        self.calls.append(record)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.latency.get(name, 0))
            if name in self.fail_first and first:
                raise ToolError("UPSTREAM_TIMEOUT: 供应商接口超时，请稍后重试同一请求")
            result = impl(**args)
        except ToolError as exc:
            record["error"] = str(exc)
            raise
        finally:
            self.active -= 1
        record["ok"] = True
        return json.dumps(result, ensure_ascii=False)


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


Date = Annotated[str, Field(description="日期 YYYY-MM-DD")]
Tool = Callable[..., Awaitable[str]]


def make_tools(env: ToolEnv, names: tuple[str, ...]) -> list[Tool]:
    async def search_hotels(
        check_in: Date,
        nights: Annotated[int, Field(ge=1, description="入住晚数")],
        adults: Annotated[int, Field(ge=1, description="成人数")],
        children: Annotated[int, Field(ge=0, description="儿童数")],
    ) -> str:
        """按入住条件查询京都可住酒店（一间房），返回各方案rate_id、早餐、可退、含税总价。"""
        args = {"check_in": check_in, "nights": nights, "adults": adults, "children": children}
        return await env.call("search_hotels", args, search_hotels_impl)

    async def get_hotel_price(check_in: Date) -> str:
        """查询某天入住1晚、2大1小家庭房的最低含税价。每次只能查一个日期。"""
        return await env.call("get_hotel_price", {"check_in": check_in}, get_hotel_price_impl)

    async def list_places() -> str:
        """列出京都候选景点：营业时间、闭馆日、最少游览分钟、门票。"""
        return await env.call("list_places", {}, list_places_impl)

    async def get_travel_minutes(
        from_place_id: Annotated[str, Field(description="出发景点place_id")],
        to_place_id: Annotated[str, Field(description="到达景点place_id")],
    ) -> str:
        """查询两个景点之间的交通分钟数。"""
        args = {"from_place_id": from_place_id, "to_place_id": to_place_id}
        return await env.call("get_travel_minutes", args, get_travel_minutes_impl)

    async def validate_itinerary(items: list[ItineraryItem], total_ticket_jpy: int) -> str:
        """校验一日行程是否满足营业时间、交通时间、门票预算等全部规则，返回ok与errors。"""
        args = {"items": items, "total_ticket_jpy": total_ticket_jpy}
        return await env.call("validate_itinerary", args, validate_itinerary_impl)

    tools = (search_hotels, get_hotel_price, list_places, get_travel_minutes, validate_itinerary)
    available = {f.__name__: f for f in tools}
    return [available[n] for n in names]


def json_schema(fn: Callable) -> dict:
    """从函数签名生成 JSON Schema（给 Claude Agent SDK / pi 用）。"""
    params: dict[str, Any] = {
        name: (p.annotation, ... if p.default is inspect.Parameter.empty else p.default)
        for name, p in inspect.signature(fn, eval_str=True).parameters.items()
    }
    schema = create_model(fn.__name__, **params).model_json_schema()
    schema.pop("title", None)
    return schema


def tool_doc(fn: Callable) -> str:
    return inspect.getdoc(fn) or ""

"""每个住宿段的酒店选择状态；单城市就是一个住宿段。选择在使用时仍按证据条件和新鲜度重新校验。"""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from backend.domain.travel_request import CITY_ALIASES, TravelRequest, TripSegment, trip_segments

type PickSource = Literal["button", "chat", "assign_confirm"]
type SelectionState = Literal["not_applicable", "awaiting", "complete", "skipped"]


class HotelPick(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    check_out: date
    evidence_id: UUID
    source: PickSource


class HotelFlow(BaseModel):
    """picks以入住日(ISO字符串)为键；skipped记录跳过时的住宿段集合，集合变了即失效。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    picks: dict[str, HotelPick] = {}
    skipped: tuple[tuple[date, date], ...] | None = None


def lodging_segments(request: TravelRequest) -> tuple[TripSegment, ...]:
    return tuple(s for s in trip_segments(request) if s.depart > s.arrive)


def flow_from_details(details: dict[str, object] | None) -> HotelFlow:
    try:
        return HotelFlow.model_validate((details or {}).get("hotel_flow") or {})
    except ValidationError:
        return HotelFlow()


def current_picks(flow: HotelFlow, request: TravelRequest) -> dict[date, HotelPick]:
    """只保留与当前住宿段日期完全一致的选择。"""
    result: dict[date, HotelPick] = {}
    for segment in lodging_segments(request):
        found = flow.picks.get(segment.arrive.isoformat())
        if found is not None and found.check_out == segment.depart:
            result[segment.arrive] = found
    return result


def is_skipped(flow: HotelFlow, request: TravelRequest) -> bool:
    segments = {(s.arrive, s.depart) for s in lodging_segments(request)}
    return bool(segments) and flow.skipped is not None and set(flow.skipped) == segments


def selection_state(flow: HotelFlow, request: TravelRequest) -> SelectionState:
    segments = lodging_segments(request)
    if not segments:
        return "not_applicable"
    if len(current_picks(flow, request)) == len(segments):
        return "complete"
    return "skipped" if is_skipped(flow, request) else "awaiting"


def with_pick(flow: HotelFlow, check_in: date, pick: HotelPick) -> HotelFlow:
    return flow.model_copy(
        update={"picks": {**flow.picks, check_in.isoformat(): pick}, "skipped": None}
    )


def with_skip(flow: HotelFlow, request: TravelRequest) -> HotelFlow:
    return flow.model_copy(
        update={"skipped": tuple((s.arrive, s.depart) for s in lodging_segments(request))}
    )


def store(details: dict[str, object] | None, flow: HotelFlow) -> dict[str, object]:
    return {**(details or {}), "hotel_flow": flow.model_dump(mode="json")}


def city_forms(city: str) -> set[str]:
    base = "".join(city.split()).casefold().removesuffix("市")
    canonical = CITY_ALIASES.get(base, base)
    return {
        form
        for form in {base, canonical, *(k for k, v in CITY_ALIASES.items() if v == canonical)}
        if form
    }


def mentions_city(text: str, city: str) -> bool:
    """text(用户原话/酒店地址/城市答案)是否提到该城市；只做有限别名的子串比较，不做地名推断。"""
    haystack = "".join(text.split()).casefold()
    return any(form in haystack for form in city_forms(city))

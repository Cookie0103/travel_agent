"""第二版的硬证据断言，输入限于服务端事实及工具事件。"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import cache
from typing import TYPE_CHECKING
from uuid import UUID

from backend.domain.geo import haversine_m
from backend.domain.opening_hours import TOKYO
from backend.domain.plans import PlanDraft
from backend.domain.travel_request import TripSegment, city_key
from data.eval_world.world import load_world
from eval.v3.cases import (
    DraftDiffCheck,
    FieldUnsetThroughCheck,
    HotelCheck,
    HotelWhere,
    NoCommissionLeakCheck,
    RequestFieldCheck,
    ToolOrderCheck,
    V2Check,
    ValidatorStatusCheck,
)
from eval.v3.facts import (
    Snapshot,
    hotel_presentations,
    hotel_segments,
    offer_city,
    offer_dates,
    picked_offer,
    request_value,
    segment_at,
)

if TYPE_CHECKING:
    from eval.v3.score import Observation, Outcome, TurnObs


_PRIVATE_KEY = re.compile(r"commission|fee[_ -]?rate|takeback|basis[_ -]?points|返佣|佣金", re.I)
_RATE_KEY = re.compile(r"rate|percent|比例|费率", re.I)


@cache
def stations() -> dict[str, tuple[float, float]]:
    world, _ = load_world()
    return {
        city_key(station.city): (station.latitude, station.longitude) for station in world.stations
    }


@cache
def commission_rates() -> frozenset[Decimal]:
    _, rates = load_world()
    return frozenset(Decimal(rate.basis_points) / 10_000 for rate in rates.values())


def number(value: object) -> Decimal | None:
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def nightly_jpy(card: Mapping[str, object]) -> Decimal | None:
    stay = card.get("stay")
    if not isinstance(stay, dict) or card.get("currency") != "JPY":
        return None
    try:
        nights = (
            date.fromisoformat(stay["end_date"]) - date.fromisoformat(stay["start_date"])
        ).days
        rooms, total = number(stay.get("rooms")), number(card.get("total"))
    except (KeyError, TypeError, ValueError):
        return None
    return (
        total / (nights * rooms)
        if total is not None and nights > 0 and rooms and rooms > 0
        else None
    )


def station_distance(card: Mapping[str, object]) -> float | None:
    stay = card.get("stay")
    city = stay.get("city") if isinstance(stay, dict) else None
    station = stations().get(city_key(city)) if isinstance(city, str) else None
    latitude = number(card.get("latitude"))
    longitude = number(card.get("longitude"))
    if station is None or latitude is None or longitude is None:
        return None
    return haversine_m(float(latitude), float(longitude), *station)


def offer_matches(
    card: Mapping[str, object], where: HotelWhere, segment: TripSegment | None
) -> bool:
    if where.breakfast is not None and card.get("breakfast") is not where.breakfast:
        return False
    if where.partner is not None:
        is_partner = card.get("partner") is True and card.get("partner_label") == "合作酒店"
        if is_partner is not where.partner:
            return False
    if where.room_tag is not None:
        tags = card.get("room_tags")
        values = [str(card.get("room_type") or "")]
        if isinstance(tags, (list, tuple)):
            values.extend(tag for tag in tags if isinstance(tag, str))
        if not any(where.room_tag in value for value in values):
            return False
    if where.in_request_city is not None and (
        segment is None or offer_city(card, segment) is not where.in_request_city
    ):
        return False
    if where.stay_matches_dates is not None and (
        segment is None or offer_dates(card, segment) is not where.stay_matches_dates
    ):
        return False
    if where.max_per_night_jpy is not None:
        cost = nightly_jpy(card)
        if cost is None or cost > Decimal(str(where.max_per_night_jpy)):
            return False
    if where.max_station_m is not None:
        distance = station_distance(card)
        if distance is None or distance > where.max_station_m:
            return False
    if where.min_rating is not None:
        rating = number(card.get("review_average"))
        if rating is None or rating < Decimal(str(where.min_rating)):
            return False
    return True


def _shown_offers(obs: Observation, check: HotelCheck) -> list[dict[str, object]]:
    turns = obs.turns[-1:] if check.turn == "last" else obs.turns
    result = []
    for turn in turns:
        for data in hotel_presentations(turn.events):
            segments = hotel_segments(data)
            if check.segment < len(segments):
                cards = segments[check.segment]["cards"]
                assert isinstance(cards, list)
                result.extend(cards)
    return result


def _hotel(check: HotelCheck, obs: Observation) -> bool:
    assert obs.final_snapshot is not None
    snapshot = obs.final_snapshot
    segment = segment_at(snapshot.request, check.segment)
    where = check.where or HotelWhere()
    if check.scope == "selected":
        if segment is None or (offer := picked_offer(snapshot, segment)) is None:
            return False
        return offer_matches(offer, where, segment)
    cards = _shown_offers(obs, check)
    if check.min_offers is not None and len(cards) < check.min_offers:
        return False
    if check.max_offers is not None and len(cards) > check.max_offers:
        return False
    matches = [offer_matches(card, where, segment) for card in cards]
    if check.min_matching is not None and sum(matches) < check.min_matching:
        return False
    if check.first_n_match is not None and (
        len(cards) < check.first_n_match or not all(matches[: check.first_n_match])
    ):
        return False
    if check.where is not None and check.min_matching is None and check.first_n_match is None:
        return any(matches)
    return True


def _draft_diff(check: DraftDiffCheck, baseline: Snapshot | None, final: PlanDraft | None) -> bool:
    previous = baseline.draft if baseline is not None else None
    if previous is None or final is None:
        return False
    old, new = previous.content, final.content
    old_stays = (old.hotel_evidence_id, old.hotel_stays)
    new_stays = (new.hotel_evidence_id, new.hotel_stays)
    old_items = [(item.place_evidence_id, item.start, item.end) for item in old.items]
    new_items = [(item.place_evidence_id, item.start, item.end) for item in new.items]
    if check.mode == "changed":
        return old_stays != new_stays or Counter(old_items) != Counter(new_items)
    assert baseline is not None and check.day is not None and check.part is not None
    if baseline.request.start_date is None or old_stays != new_stays:
        return False
    day = baseline.request.start_date + timedelta(days=check.day - 1)

    def in_part(item: tuple[UUID, datetime, datetime]) -> bool:
        value = item[1].astimezone(TOKYO)
        part = "morning" if value.hour < 12 else "afternoon" if value.hour < 18 else "evening"
        return value.date() == day and part == check.part

    if Counter(item for item in old_items if not in_part(item)) != Counter(
        item for item in new_items if not in_part(item)
    ):
        return False
    return not check.require_change or Counter(old_items) != Counter(new_items)


def _request_field(check: RequestFieldCheck, snapshot: Snapshot) -> bool:
    value = request_value(snapshot.request, check.field)
    expected = check.value
    if check.field == "city" and isinstance(value, str) and isinstance(expected, str):
        value, expected = city_key(value), city_key(expected)
    if check.field == "lodging_budget_upper" and expected is not None:
        expected_money = number(expected)
        equal = value == expected_money if expected_money is not None else False
    else:
        equal = value == expected
    match check.op:
        case "equals":
            return equal
        case "not_equals":
            return not equal
        case "set":
            return value is not None
        case "unset":
            return value is None
        case "contains" | "not_contains":
            assert isinstance(expected, str) and isinstance(value, list)
            hit = any(expected in item for item in value)
            return hit if check.op == "contains" else not hit


def _has_private(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            if _PRIVATE_KEY.search(name):
                return True
            if _RATE_KEY.search(name) and (rate := number(item)) is not None:
                rates = commission_rates()
                if (
                    rate in rates
                    or rate / 10_000 in rates
                    or ("percent" in name.casefold() and rate / 100 in rates)
                ):
                    return True
            if _has_private(item):
                return True
    if isinstance(value, (tuple, list)):
        return any(_has_private(item) for item in value)
    return False


def _tool_order(check: ToolOrderCheck, turns: Sequence[TurnObs]) -> bool:
    finished = False
    for turn in turns:
        for event in turn.events:
            if event.kind == "tool_started" and event.tool_name == check.then:
                return finished
            if event.kind == "tool_finished" and event.tool_name == check.first:
                finished = True
    return False


def evaluate(check: V2Check, obs: Observation) -> tuple[Outcome, str]:
    snapshot = obs.final_snapshot
    if snapshot is None:
        return "fail", "无终态服务端事实"
    match check:
        case HotelCheck():
            success = _hotel(check, obs)
        case ValidatorStatusCheck():
            matching = (
                [row.status for row in snapshot.draft.validation.checks if row.code == check.code]
                if snapshot.draft
                else []
            )
            success = (
                bool(matching)
                if check.expect == "present"
                else (
                    snapshot.draft is not None
                    and not {"unknown", "conflict"}.intersection(matching)
                )
            )
        case DraftDiffCheck():
            success = _draft_diff(check, obs.before_steps.get(check.after_step), snapshot.draft)
        case FieldUnsetThroughCheck():
            requests = [
                request for index, request in obs.step_requests if index <= check.through_step
            ]
            success = all(request_value(request, check.field) is None for request in requests)
        case RequestFieldCheck():
            success = _request_field(check, snapshot)
        case NoCommissionLeakCheck():
            payloads = [
                event.presentation
                for turn in obs.turns
                for event in turn.events
                if event.kind == "presentation"
            ]
            success = not _has_private(
                (
                    payloads,
                    obs.state,
                    obs.card_payloads,
                    tuple(snapshot.picked.values()),
                    snapshot.draft.model_dump(mode="json") if snapshot.draft else None,
                )
            )
        case ToolOrderCheck():
            success = _tool_order(check, obs.turns)
    return ("pass" if success else "fail"), ""

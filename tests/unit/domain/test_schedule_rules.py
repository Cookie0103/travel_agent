"""第二阶段规则 4–11 的行程校验入口回归。"""

from datetime import time

import pytest

from backend.domain.evidence import EvidenceRecord
from backend.domain.hotels import quote
from backend.domain.itinerary import ItineraryProposal, ValidationReport
from backend.domain.travel_request import TravelRequest
from backend.domain.validator import validate_itinerary
from backend.providers.hotel_fixture import load_rates
from tests.unit.domain.test_itinerary import NOW, item, place, record, request


def report_for_stop(
    current: TravelRequest, start: str, end: str, *, room_type: str | None = None
) -> ValidationReport:
    destination = record(place().model_copy(update={"opening_hours": "24/7"}), current)
    records: tuple[EvidenceRecord, ...] = (destination,)
    hotel_id = None
    if room_type is not None:
        rates, _ = load_rates()
        offer = quote(rates[0], current, NOW)
        assert offer is not None
        hotel = record(offer.model_copy(update={"room_type": room_type}), current)
        records += (hotel,)
        hotel_id = hotel.evidence_id
    proposal = ItineraryProposal(
        expected_revision=current.revision,
        items=(item(destination, start, end),),
        hotel_evidence_id=hotel_id,
    )
    return validate_itinerary(current, proposal, records, NOW)


@pytest.mark.parametrize("start,violates", [("11:59", True), ("12:00", False), ("12:01", False)])
def test_arrival_boundary_uses_first_day_local_start(start: str, violates: bool) -> None:
    current = request().model_copy(
        update={"hard_constraints": ("第一天抵达：中午 12:00 左右",)},
    )
    result = report_for_stop(current, f"2026-11-03T{start}+09:00", "2026-11-03T13:00+09:00")
    assert (
        any(c.code == "arrival_boundary" and c.status == "conflict" for c in result.checks)
        is violates
    )


@pytest.mark.parametrize("end,violates", [("14:31", True), ("14:30", False), ("14:29", False)])
def test_departure_boundary_reserves_station_buffer(end: str, violates: bool) -> None:
    current = request().model_copy(
        update={
            "hard_constraints": ("3号中午12点抵达成田机场", "5号下午3点坐火车返程"),
        },
    )
    result = report_for_stop(current, "2026-11-05T13:00+09:00", f"2026-11-05T{end}+09:00")
    assert (
        any(c.code == "departure_boundary" and c.status == "conflict" for c in result.checks)
        is violates
    )


@pytest.mark.parametrize("named,violates", [("未安排景点", True), (None, False)])
def test_explicit_must_visit_matches_catalog_name(named: str | None, violates: bool) -> None:
    current = request().model_copy(
        update={"hard_constraints": ("必须去：" + (named or place().name),)},
    )
    result = report_for_stop(current, "2026-11-03T10:00+09:00", "2026-11-03T11:00+09:00")
    assert any(c.code == "must_visit" and c.status == "conflict" for c in result.checks) is violates


@pytest.mark.parametrize(
    "room,status",
    [
        ("喫煙ダブル ドミトリー", "conflict"),
        ("禁煙ツイン個室", "verified"),
        ("普通客房", "unknown"),
    ],
)
def test_room_preference_separates_conflict_and_unknown(room: str, status: str) -> None:
    current = request().model_copy(
        update={"hard_constraints": ("房型：禁烟", "床型：双床", "住宿：独立房间")},
    )
    result = report_for_stop(
        current, "2026-11-03T10:00+09:00", "2026-11-03T11:00+09:00", room_type=room
    )
    checks = [c.status for c in result.checks if c.code == "room_preference"]
    assert checks == [status]


@pytest.mark.parametrize("start,violates", [("07:29", True), ("07:30", False)])
def test_wake_time_warns_on_early_activity(start: str, violates: bool) -> None:
    current = request().model_copy(update={"soft_constraints": ("平时起床：7:30 左右",)})
    report = report_for_stop(current, f"2026-11-04T{start}+09:00", "2026-11-04T08:30+09:00")
    assert any(c.code == "daily_hours" and c.status == "unknown" for c in report.checks) is violates


@pytest.mark.parametrize("end,violates", [(time(20, 1), True), (time(20), False)])
def test_child_day_end_is_advisory(end: time, violates: bool) -> None:
    current = request().model_copy(update={"child_ages": (8,)})
    report = report_for_stop(current, "2026-11-04T19:00+09:00", f"2026-11-04T{end:%H:%M}+09:00")
    assert (
        any(c.code == "child_day_limits" and c.status == "unknown" for c in report.checks)
        is violates
    )


@pytest.mark.parametrize("minutes,violates", [(181, True), (180, False), (179, False)])
def test_daily_movement_uses_listed_route_estimates(minutes: int, violates: bool) -> None:
    from datetime import datetime

    from backend.domain.itinerary import RouteEstimate

    current = request()
    a = place().model_copy(update={"place_id": "move:a"})
    b = place().model_copy(update={"place_id": "move:b"})
    first, second = record(a, current), record(b, current)
    route = record(
        RouteEstimate(
            from_place_id=a.place_id,
            to_place_id=b.place_id,
            transport="walk",
            departure=datetime.fromisoformat("2026-11-03T10:00+09:00"),
            minutes=minutes,
            confidence="estimate",
        ),
        current,
    )
    proposal = ItineraryProposal(
        expected_revision=current.revision,
        items=(
            item(first, "2026-11-03T09:00+09:00", "2026-11-03T10:00+09:00"),
            item(second, "2026-11-03T14:00+09:00", "2026-11-03T15:00+09:00", route),
        ),
    )
    result = validate_itinerary(current, proposal, (first, second, route), NOW)
    assert (
        any(c.code == "daily_movement" and c.status == "unknown" for c in result.checks) is violates
    )


@pytest.mark.parametrize("return_near_start,violates", [(True, True), (False, False)])
def test_long_city_roundtrip_warns_when_returning_near_first_stop(
    return_near_start: bool,
    violates: bool,
) -> None:
    current = request()
    places = tuple(
        record(
            place().model_copy(update={"place_id": f"roundtrip:{i}", "latitude": latitude}), current
        )
        for i, latitude in enumerate((35.00, 35.15, 35.005 if return_near_start else 35.3))
    )
    proposal = ItineraryProposal(
        expected_revision=current.revision,
        items=tuple(
            item(target, f"2026-11-03T{hour:02d}:00+09:00", f"2026-11-03T{hour + 1:02d}:00+09:00")
            for hour, target in zip((9, 12, 15), places, strict=True)
        ),
    )
    result = validate_itinerary(current, proposal, places, NOW)
    assert (
        any(c.code == "day_backtrack" and c.status == "unknown" for c in result.checks) is violates
    )


@pytest.mark.parametrize("returns,violates", [(False, True), (True, False)])
def test_overnight_last_stop_compares_to_the_chosen_hotel(returns: bool, violates: bool) -> None:
    current = request()
    rates, _ = load_rates()
    offer = quote(rates[0], current, NOW)
    assert offer is not None
    destination = (
        place().model_copy(update={"name": offer.hotel_name, "category": "hotel"})
        if returns
        else place()
    )
    stop, hotel = record(destination, current), record(offer, current)
    proposal = ItineraryProposal(
        expected_revision=current.revision,
        items=(item(stop),),
        hotel_evidence_id=hotel.evidence_id,
    )
    result = validate_itinerary(current, proposal, (stop, hotel), NOW)
    assert (
        any(c.code == "hotel_return" and c.status == "unknown" for c in result.checks) is violates
    )


@pytest.mark.parametrize(
    "outside_shift,hotel_changed,expected",
    [(False, False, "verified"), (True, False, "conflict"), (False, True, "conflict")],
)
def test_day_limited_edit_checks_unmentioned_slots_and_hotels(
    outside_shift: bool,
    hotel_changed: bool,
    expected: str,
) -> None:
    from uuid import uuid4

    from backend.domain.itinerary_revision import edit_scope_check

    current = request()
    destination = record(place(), current)
    first = item(destination, "2026-11-03T10:00+09:00", "2026-11-03T11:00+09:00")
    second = item(destination, "2026-11-04T10:00+09:00", "2026-11-04T11:00+09:00")
    before = ItineraryProposal(expected_revision=current.revision, items=(first, second))
    updated = before.model_copy(
        update={
            "items": (
                first.model_copy(update={"note": "更动首日"}) if outside_shift else first,
                second.model_copy(update={"note": "调整第二天"}),
            ),
            "hotel_evidence_id": uuid4() if hotel_changed else None,
        }
    )
    result = edit_scope_check(
        "只改第二天，其他不动", current, before, updated, {destination.evidence_id: place()}
    )
    assert result is not None and result.status == expected


def test_limited_afternoon_edit_keeps_evening_and_uses_historical_place_identity() -> None:
    from uuid import uuid4

    from backend.domain.itinerary_revision import edit_scope_check

    current = request()
    destination = record(place(), current)
    first = item(destination, "2026-11-04T14:00+09:00", "2026-11-04T15:00+09:00")
    last = item(destination, "2026-11-04T18:00+09:00", "2026-11-04T19:00+09:00")
    before = ItineraryProposal(expected_revision=current.revision, items=(first, last))
    refreshed = uuid4()
    inside = first.model_copy(update={"note": "换成室内活动"})
    evening = last.model_copy(update={"place_evidence_id": refreshed})
    text = "只把第二天下午的安排换成室内活动，其他时间和安排不要动。"

    for proposal, status in (
        (before.model_copy(update={"items": (inside, evening)}), "verified"),
        (
            before.model_copy(
                update={"items": (inside, evening.model_copy(update={"note": "改了晚间"}))}
            ),
            "conflict",
        ),
    ):
        result = edit_scope_check(
            text,
            current,
            before,
            proposal,
            {refreshed: place()},
            historical_places={destination.evidence_id: place().place_id},
        )
        assert result is not None and result.status == status

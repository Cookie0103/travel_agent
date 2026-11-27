"""第二批规则在纯行程校验入口的边界与缺失数据回归。"""

from datetime import date, datetime, timedelta
from uuid import UUID

import pytest

from backend.domain.evidence import EvidenceRecord
from backend.domain.hotel_details import StoredHotelDetails
from backend.domain.hotels import quote
from backend.domain.itinerary import HotelStay, ItineraryProposal
from backend.domain.opening_hours import opening_state
from backend.domain.validator import validate_itinerary
from backend.providers.hotel_fixture import load_rates
from tests.unit.domain.test_itinerary import NOW, item, place, record, request


@pytest.mark.parametrize(
    "probability,alternative,expected",
    [
        (59, False, None),
        (60, False, "conflict"),
        (60, True, "verified"),
        (None, False, "unknown"),
    ],
)
def test_rain_rule_uses_a_verified_indoor_alternative_at_the_sixty_percent_boundary(
    probability: int | None, alternative: bool, expected: str | None
) -> None:
    current = request()
    park = place().model_copy(update={"category": "park", "opening_hours": "24/7", "indoor": None})
    stop = record(park, current)
    records: tuple[EvidenceRecord, ...] = (stop,)
    alternate: UUID | None = None
    if alternative:
        museum = park.model_copy(update={"category": "museum", "place_id": "fixture:indoor-museum"})
        museum_record = record(museum, current)
        alternate = museum_record.evidence_id
        records += (museum_record,)
    proposal = ItineraryProposal(
        expected_revision=current.revision,
        items=(item(stop).model_copy(update={"rain_alternative_place_evidence_id": alternate}),),
    )
    weather = {(park.city, date(2026, 11, 3)): probability}
    result = validate_itinerary(current, proposal, records, NOW, weather=weather)
    assert next((c.status for c in result.checks if c.code == "rain_plan"), None) == expected


@pytest.mark.parametrize(
    "start,expected",
    [
        ("2026-12-28T13:00+09:00", "open"),
        ("2026-12-29T13:00+09:00", "closed"),
        ("2027-01-03T13:00+09:00", "closed"),
        ("2027-01-04T13:00+09:00", "open"),
        ("2027-01-04T12:00+09:00", "closed"),
    ],
)
def test_opening_checks_fixed_closure_and_lunch_boundary(start: str, expected: str) -> None:
    moment = datetime.fromisoformat(start)
    assert (
        opening_state(
            "Mo-Su 09:00-12:00,13:00-17:00; Dec 29-Jan 3 off",
            moment,
            moment + timedelta(minutes=30),
        )
        == expected
    )


@pytest.mark.parametrize(
    "minute,hours,closes", [("17:00", "10:00-18:00", False), ("17:01", None, True)]
)
def test_last_admission_and_reservation_emit_correct_levels(
    minute: str, hours: str | None, closes: bool
) -> None:
    current = request().model_copy(update={"city": "东京"})
    museum = place().model_copy(
        update={"city": "东京", "name": "三鹰之森吉卜力美术馆", "opening_hours": hours}
    )
    stop = record(museum, current)
    proposal = ItineraryProposal(
        expected_revision=current.revision,
        items=(item(stop, f"2026-11-03T{minute}+09:00", "2026-11-03T17:45+09:00"),),
    )
    checks = validate_itinerary(current, proposal, (stop,), NOW).checks
    assert next(c.status for c in checks if c.code == "opening_hours") == (
        "conflict" if closes else "verified"
    )
    assert "入场前完成预约" in next(c.message for c in checks if c.code == "reservation_required")


def test_peak_reminder_uses_inclusive_japan_holiday_boundary() -> None:
    first, last = date(2027, 4, 28), date(2027, 4, 29)
    current = request().model_copy(update={"start_date": first, "end_date": last})
    stop = record(place().model_copy(update={"opening_hours": "24/7"}), current)
    for day in (first, last):
        proposal = ItineraryProposal(
            expected_revision=current.revision,
            items=(item(stop, f"{day}T13:00+09:00", f"{day}T14:00+09:00"),),
        )
        checks = validate_itinerary(current, proposal, (stop,), NOW).checks
        assert any(c.code == "travel_peak" and "黄金周" in c.message for c in checks) is (
            day == last
        )


@pytest.mark.parametrize(
    "minute,note,flags",
    [
        ("23:00", "到酒店办理入住并随身带行李", set()),
        ("23:01", "回酒店休息", {"hotel_change_luggage", "hotel_stay_time"}),
        ("22:59", "到酒店办理入住", {"hotel_change_luggage"}),
    ],
)
def test_switching_hotels_warns_on_luggage_and_latest_checkin(
    minute: str,
    note: str,
    flags: set[str],
) -> None:
    from backend.domain.regional_rules import stay_timing_checks

    current = request()
    rates, _ = load_rates()
    first, second = quote(rates[0], current, NOW), quote(rates[-1], current, NOW)
    assert first is not None and second is not None
    second = second.model_copy(update={"hotel_id": "second-hotel"})
    done = record(first, current)
    next_hotel = record(second, current).model_copy(
        update={
            "display_details": StoredHotelDetails(
                checkin_time="15:00", latest_checkin_time="23:00", checkout_time="10:00"
            )
        }
    )
    hotel_place = place().model_copy(update={"name": second.hotel_name, "category": "hotel"})
    stop = record(hotel_place, current)
    start, change, end = date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)
    proposal = ItineraryProposal(
        expected_revision=current.revision,
        items=(
            item(stop, f"{change}T{minute}+09:00", f"{change}T23:50+09:00").model_copy(
                update={"note": note}
            ),
        ),
        hotel_stays=(
            HotelStay(check_in=start, check_out=change, hotel_evidence_id=done.evidence_id),
            HotelStay(check_in=change, check_out=end, hotel_evidence_id=next_hotel.evidence_id),
        ),
    )
    checks = stay_timing_checks(
        current, proposal, [hotel_place], {r.evidence_id: r for r in (stop, done, next_hotel)}
    )
    assert {c.code for c in checks if c.status == "unknown"} == flags

"""每个住宿段的酒店选择状态：单城市也是一个住宿段；跳过只对当前住宿段集合有效。"""

from datetime import date
from uuid import uuid4

from backend.domain.hotel_flow import (
    HotelFlow,
    HotelPick,
    flow_from_details,
    lodging_segments,
    selection_state,
    with_pick,
    with_skip,
)
from backend.domain.travel_request import TravelRequest, TripSegment

SINGLE = TravelRequest(
    city="京都", start_date=date(2026, 11, 20), end_date=date(2026, 11, 22), adults=2, rooms=1
)
MULTI = TravelRequest(
    city="京都",
    start_date=date(2026, 11, 20),
    end_date=date(2026, 11, 23),
    segments=(
        TripSegment(city="京都", arrive=date(2026, 11, 20), depart=date(2026, 11, 22)),
        TripSegment(city="大阪", arrive=date(2026, 11, 22), depart=date(2026, 11, 23)),
    ),
)


def pick(check_out: date) -> HotelPick:
    return HotelPick(check_out=check_out, evidence_id=uuid4(), source="chat")


def test_single_city_is_one_lodging_segment() -> None:
    assert [(s.arrive, s.depart) for s in lodging_segments(SINGLE)] == [
        (date(2026, 11, 20), date(2026, 11, 22))
    ]
    assert lodging_segments(TravelRequest()) == ()
    day = SINGLE.model_copy(update={"end_date": date(2026, 11, 20)})
    assert lodging_segments(day) == ()
    assert selection_state(HotelFlow(), day) == "not_applicable"


def test_state_follows_picks_and_skip() -> None:
    flow = HotelFlow()
    assert selection_state(flow, MULTI) == "awaiting"
    flow = with_pick(flow, date(2026, 11, 20), pick(date(2026, 11, 22)))
    assert selection_state(flow, MULTI) == "awaiting"
    flow = with_pick(flow, date(2026, 11, 22), pick(date(2026, 11, 23)))
    assert selection_state(flow, MULTI) == "complete"
    skipped = with_skip(HotelFlow(), MULTI)
    assert selection_state(skipped, MULTI) == "skipped"
    assert selection_state(skipped, SINGLE) == "awaiting"  # 住宿段集合变了，跳过失效


def test_pick_for_changed_dates_does_not_count() -> None:
    flow = with_pick(HotelFlow(), date(2026, 11, 20), pick(date(2026, 11, 21)))  # 退房日不同
    assert selection_state(flow, SINGLE) == "awaiting"


def test_choosing_after_skip_clears_the_skip_and_roundtrips_through_details() -> None:
    flow = with_pick(with_skip(HotelFlow(), SINGLE), date(2026, 11, 20), pick(date(2026, 11, 22)))
    assert flow.skipped is None and selection_state(flow, SINGLE) == "complete"
    again = flow_from_details({"hotel_flow": flow.model_dump(mode="json")})
    assert again == flow
    assert flow_from_details(None) == HotelFlow() == flow_from_details({"hotel_flow": "坏数据"})


def test_skipped_lodging_is_unknown_not_a_conflict_in_the_validator() -> None:
    from datetime import UTC, datetime

    from backend.domain.validator import stay_costs
    from tests.test_multi_city_itinerary import multi_city_example

    request, proposal, _ = multi_city_example()
    bare = proposal.model_copy(update={"hotel_stays": ()})
    _, missing = stay_costs(request, bare, {}, datetime.now(UTC))
    assert {c.status for c in missing} == {"conflict"}
    _, skipped = stay_costs(
        request.model_copy(update={"lodging_skipped": True}), bare, {}, datetime.now(UTC)
    )
    assert {(c.code, c.status) for c in skipped} == {("hotel_stay_skipped", "unknown")}
    assert len(skipped) == len(missing)

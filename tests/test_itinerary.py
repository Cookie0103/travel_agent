"""R06：纯校验器的闭馆、跨午夜、未知费用、证据范围与时间冲突失败路径。"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.domain.catalog import Place
from backend.domain.evidence import EvidenceKind, EvidenceRecord, evidence_conditions
from backend.domain.hotels import HotelOffer, quote
from backend.domain.itinerary import (
    ItineraryProposal,
    ProposedItem,
    RouteEstimate,
    ValidationReport,
)
from backend.domain.travel_request import TravelRequest
from backend.domain.validator import validate_itinerary
from backend.providers.hotel_fixture import load_rates
from backend.providers.routes_fixture import estimate, load_routes
from data.import_catalog import load_snapshot

NOW = datetime.now(UTC)


def request() -> TravelRequest:
    return TravelRequest(
        city="京都",
        start_date=date(2026, 11, 3),
        end_date=date(2026, 11, 5),
        adults=2,
        child_ages=(),
        rooms=1,
        transport="walk",
        budget=Decimal("50000"),
        revision=1,
    )


def place(id: str = "osm:way/57111281") -> Place:
    return next(p for p in load_snapshot() if isinstance(p, Place) and p.place_id == id)


def record(
    value: Place | RouteEstimate | HotelOffer, current: TravelRequest | None = None
) -> EvidenceRecord:
    current = current or request()
    kind: EvidenceKind = (
        "place"
        if isinstance(value, Place)
        else "route"
        if isinstance(value, RouteEstimate)
        else "hotel_offer"
    )
    entity = (
        value.place_id
        if isinstance(value, Place)
        else str(value.route_id)
        if isinstance(value, RouteEstimate)
        else str(value.offer_id)
    )
    return EvidenceRecord(
        entity_id=entity,
        field_path=kind,
        value=value.model_dump(mode="json"),
        kind=kind,
        request_revision=current.revision,
        conditions=evidence_conditions(current, kind),
        provider="test-fixture",
        source_ref="fixture:test",
        content_version="1",
        retrieved_at=NOW - timedelta(seconds=1),
        valid_until=NOW + timedelta(minutes=5),
        data_mode="fixture",
    )


def item(
    evidence: EvidenceRecord,
    start: str = "2026-11-03T10:00+09:00",
    end: str = "2026-11-03T11:00+09:00",
    route: EvidenceRecord | None = None,
) -> ProposedItem:
    return ProposedItem(
        place_evidence_id=evidence.evidence_id,
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        route_evidence_id=route.evidence_id if route else None,
    )


def test_closed_visit_conflicts_and_repair_keeps_unknown_budget() -> None:
    evidence = record(place())
    bad = ItineraryProposal(
        expected_revision=1,
        items=(item(evidence, "2026-11-03T18:00+09:00", "2026-11-03T19:00+09:00"),),
    )
    report = validate_itinerary(request(), bad, (evidence,), NOW)
    assert report.status == "conflict"
    feedback = report.feedback()["checks"]
    assert isinstance(feedback, list) and feedback[0]["code"] == "opening_hours"
    repaired = bad.model_copy(update={"items": (item(evidence),)})
    report = validate_itinerary(request(), repaired, (evidence,), NOW)
    assert report.status == "partial" and not any(c.status == "conflict" for c in report.checks)
    assert any(c.code == "other_costs" and c.status == "unknown" for c in report.checks)


@pytest.mark.parametrize(
    "hours",
    ["Mo-Su 09:00-17:00", "; ".join(["Mo-Su 09:00-17:00"] * 50)],
    ids=["normal-hours", "long-hours"],
)
def test_closed_visit_feedback_identifies_local_times_and_source_hours(hours: str) -> None:
    """R06/R17：闭馆冲突提供具体日本时段，模型不用盲改；TRACE不含地点原文。"""
    source = place().model_copy(update={"opening_hours": hours})
    evidence = record(source)
    proposal = ItineraryProposal(
        expected_revision=1,
        items=(item(evidence, "2026-11-03T09:00+00:00", "2026-11-03T10:00+00:00"),),
    )
    report = validate_itinerary(request(), proposal, (evidence,), NOW)
    checks = report.feedback()["checks"]
    assert isinstance(checks, list)
    conflict = next(entry for entry in checks if entry["code"] == "opening_hours")
    assert conflict["status"] == "conflict" and conflict["subject"] == "item:0"
    assert "2026-11-03" in conflict["message"]
    assert "18:00" in conflict["message"] and "19:00" in conflict["message"]
    assert "Mo-Su 09:00-17:00" in conflict["message"]
    assert len(conflict["message"]) < 500
    label = next(entry.trace_label for entry in report.checks if entry.code == "opening_hours")
    assert "@d1i1" in label and "18:00" in label and "19:00" in label
    assert source.name not in label


@pytest.mark.parametrize(
    ("start", "end", "hours", "expected"),
    [
        ("2026-11-03T23:30+09:00", "2026-11-04T00:30+09:00", "Mo-Su 22:00-02:00", "verified"),
        ("2026-11-03T23:30+09:00", "2026-11-04T03:00+09:00", "Mo-Su 22:00-02:00", "conflict"),
        ("2026-11-03T01:00+00:00", "2026-11-03T02:00+00:00", None, "unknown"),
    ],
)
def test_timezone_full_visit_and_missing_opening_hours(
    start: str, end: str, hours: str | None, expected: str
) -> None:
    evidence = record(place().model_copy(update={"opening_hours": hours}))
    proposal = ItineraryProposal(expected_revision=1, items=(item(evidence, start, end),))
    report = validate_itinerary(request(), proposal, (evidence,), NOW)
    assert next(c.status for c in report.checks if c.code == "opening_hours") == expected


@pytest.mark.parametrize("change", ["scope", "departure", "gap", "missing"])
def test_route_scope_departure_gap_and_missing_are_distinct(change: str) -> None:
    first, second = record(place()), record(place("osm:way/314446153"))
    rates, _ = load_routes()
    route = estimate(
        rates,
        request(),
        first.entity_id,
        second.entity_id,
        datetime.fromisoformat("2026-11-03T11:00+09:00"),
    )
    if change == "scope":
        route = route.model_copy(update={"to_place_id": "wrong"})
    if change == "departure":
        route = route.model_copy(
            update={"departure": datetime.fromisoformat("2026-11-03T10:30+09:00")}
        )
    evidence = record(route)
    visit = item(
        second,
        "2026-11-03T11:05+09:00" if change == "gap" else "2026-11-03T12:00+09:00",
        "2026-11-03T13:00+09:00",
        None if change == "missing" else evidence,
    )
    proposal = ItineraryProposal(expected_revision=1, items=(item(first), visit))
    report = validate_itinerary(
        request(),
        proposal,
        (first, second) if change == "missing" else (first, second, evidence),
        NOW,
    )
    result = next(c for c in report.checks if c.subject.startswith("route:"))
    assert (
        result.code
        == {
            "scope": "route_scope",
            "departure": "route_departure",
            "gap": "route_gap",
            "missing": "route_missing",
        }[change]
    )
    assert result.status == ("unknown" if change == "missing" else "conflict")


def test_repeated_place_at_different_times_allowed_but_overlap_and_departure_conflict() -> None:
    evidence = record(place())
    current = request().model_copy(update={"departure_time": time(10, 30)})
    proposal = ItineraryProposal(
        expected_revision=1,
        items=(item(evidence), item(evidence, "2026-11-03T10:30+09:00", "2026-11-03T12:00+09:00")),
    )
    report = validate_itinerary(current, proposal, (evidence,), NOW)
    assert {c.code for c in report.checks if c.status == "conflict"} == {
        "overlap",
        "departure_time",
    }
    proposal = proposal.model_copy(
        update={
            "items": (
                item(evidence, "2026-11-03T11:00+09:00", "2026-11-03T12:00+09:00"),
                item(evidence, "2026-11-03T14:00+09:00", "2026-11-03T15:00+09:00"),
            )
        }
    )
    assert validate_itinerary(current, proposal, (evidence,), NOW).status == "partial"


def test_unknown_route_never_makes_duration_or_fare_up() -> None:
    rates, version = load_routes()
    route = estimate(rates, request(), "unknown", "also-unknown", NOW)
    assert route.confidence == "unknown" and route.minutes is None and route.fare is None
    assert len(version) == 64
    with pytest.raises(ValidationError):
        RouteEstimate.model_validate({**route.model_dump(), "minutes": 10})
    transit = request().model_copy(update={"transport": "transit", "child_ages": (6,)})
    route = estimate(rates, transit, "osm:way/57111281", "osm:way/314446153", NOW)
    assert route.fare == Decimal(690)
    assert (
        estimate(
            rates,
            transit.model_copy(update={"child_ages": None}),
            route.from_place_id,
            route.to_place_id,
            NOW,
        ).fare
        is None
    )


def test_missing_tax_is_unknown_and_known_hotel_exceeds_budget_is_conflict() -> None:
    rates, _ = load_rates()
    offer = quote(rates[0], request(), NOW)
    assert offer is not None and offer.total is not None
    destination = record(place())
    hotel = record(offer.model_copy(update={"tax_amount": None}))
    proposal = ItineraryProposal(
        expected_revision=1, items=(item(destination),), hotel_evidence_id=hotel.evidence_id
    )
    report = validate_itinerary(request(), proposal, (destination, hotel), NOW)
    assert report.known_cost == offer.base_amount + (offer.fee_amount or 0) and any(
        c.code == "hotel_total" and c.status == "unknown" for c in report.checks
    )
    hotel = record(offer)
    proposal = proposal.model_copy(update={"hotel_evidence_id": hotel.evidence_id})
    report = validate_itinerary(
        request().model_copy(update={"budget": Decimal(1)}), proposal, (destination, hotel), NOW
    )
    assert report.known_cost == offer.total and report.status == "conflict"


def test_stale_wrong_kind_or_internal_hotel_scope_fails_whole_validation() -> None:
    destination = record(place())
    proposal = ItineraryProposal(expected_revision=1, items=(item(destination),))
    with pytest.raises(ValueError, match="失效"):
        validate_itinerary(
            request(), proposal, (destination.model_copy(update={"valid_until": NOW}),), NOW
        )
    with pytest.raises(ValueError, match="place"):
        validate_itinerary(
            request(), proposal, (destination.model_copy(update={"kind": "article"}),), NOW
        )
    rates, _ = load_rates()
    offer = quote(rates[0], request().model_copy(update={"rooms": 2}), NOW)
    assert offer is not None
    hotel = record(offer)
    with pytest.raises(ValueError, match="条件"):
        validate_itinerary(
            request(),
            proposal.model_copy(update={"hotel_evidence_id": hotel.evidence_id}),
            (destination, hotel),
            NOW,
        )
    forged = proposal.model_copy(update={"hotel_evidence_id": uuid4()})
    with pytest.raises(ValueError, match="缺失"):
        validate_itinerary(request(), forged, (destination,), NOW)


@pytest.mark.parametrize("live", [False, True], ids=["fixture", "live-shape"])
def test_current_hotel_quote_survives_legacy_location_projection(live: bool) -> None:
    """P84：旧报价JSON不含住宿地点，当前完整条件仍由Evidence保存并核验。"""
    current = request().model_copy(update={"hotel_search_location": "京都"})
    offer = quote(load_rates()[0][0], current, NOW)
    assert offer is not None and offer.total is not None
    if live:
        offer = offer.model_copy(update={"data_mode": "live", "included_total": offer.total})
    destination, hotel = record(place(), current), record(offer, current)
    restored = HotelOffer.model_validate(hotel.value)
    assert restored.request.hotel_search_location is None
    assert hotel.conditions["hotel_search_location"] == "京都"
    proposal = ItineraryProposal(
        expected_revision=1, items=(item(destination),), hotel_evidence_id=hotel.evidence_id
    )
    report = validate_itinerary(current, proposal, (destination, hotel), NOW)
    assert report.known_cost == offer.total
    assert not any(c.code == "hotel_total" and c.status == "conflict" for c in report.checks)
    changed = current.model_copy(update={"hotel_search_location": "京都駅"})
    with pytest.raises(ValueError, match="失效"):
        validate_itinerary(changed, proposal, (destination, hotel), NOW)


def test_missing_source_never_proves_open_or_known_cost() -> None:
    destination = record(place()).model_copy(update={"provider": None})
    report = validate_itinerary(
        request(),
        ItineraryProposal(expected_revision=1, items=(item(destination),)),
        (destination,),
        NOW,
    )
    assert any(c.code == "opening_hours" and c.status == "unknown" for c in report.checks)


def test_unknown_route_with_departure_after_next_visit_still_conflicts() -> None:
    """R06审查回归：未知耗时不能遮住已确定的出发时间冲突。"""
    current = request().model_copy(update={"transport": "taxi"})
    first, second = record(place(), current), record(place("osm:way/314446153"), current)
    rates, _ = load_routes()
    route = record(
        estimate(
            rates,
            current,
            first.entity_id,
            second.entity_id,
            datetime.fromisoformat("2026-11-05T13:00+09:00"),
        ),
        current,
    )
    proposal = ItineraryProposal(
        expected_revision=1,
        items=(
            item(first, "2026-11-05T10:00+09:00", "2026-11-05T11:00+09:00"),
            item(second, "2026-11-05T12:00+09:00", "2026-11-05T13:00+09:00", route),
        ),
    )
    report = validate_itinerary(current, proposal, (first, second, route), NOW)
    assert report.status == "conflict" and any(
        c.code == "route_departure" and c.status == "conflict" for c in report.checks
    )


def test_incomplete_total_with_known_base_above_budget_still_conflicts() -> None:
    """R06审查回归：非负费用给出的已知下界超过预算，缺税也属于硬冲突。"""
    rates, _ = load_rates()
    current = request().model_copy(update={"budget": Decimal(100)})
    offer = quote(rates[4], current, NOW)
    assert current.budget is not None
    assert offer is not None and offer.total is None and offer.base_amount > current.budget
    destination, hotel = record(place(), current), record(offer, current)
    proposal = ItineraryProposal(
        expected_revision=1, items=(item(destination),), hotel_evidence_id=hotel.evidence_id
    )
    report = validate_itinerary(current, proposal, (destination, hotel), NOW)
    assert report.known_cost >= offer.base_amount and report.status == "conflict"
    assert any(c.code == "hotel_total" and c.status == "unknown" for c in report.checks)


def route_report(
    route: RouteEstimate, mode: str = "live", transport: str = "walk"
) -> list[tuple[str, str, str]]:
    current = request().model_copy(update={"transport": transport})
    first, second = record(place(), current), record(place("osm:way/314446153"), current)
    stored = record(route, current).model_copy(update={"data_mode": mode})
    proposal = ItineraryProposal(
        expected_revision=1,
        items=(
            item(first),
            item(second, "2026-11-03T12:00+09:00", "2026-11-03T13:00+09:00", stored),
        ),
    )
    report = validate_itinerary(current, proposal, (first, second, stored), NOW)
    assert report.status != "complete"  # other_costs 永远未知
    return [(c.status, c.code, c.message) for c in report.checks]


def google_route(**values: object) -> RouteEstimate:
    base: dict[str, object] = {
        "from_place_id": place().place_id,
        "to_place_id": "osm:way/314446153",
        "transport": "walk",
        "departure": datetime.fromisoformat("2026-11-03T11:00+09:00"),
        "confidence": "estimate",
        "minutes": 20,
    }
    return RouteEstimate.model_validate({**base, **values})


def test_live_route_failure_message_differs_from_offline_table_miss() -> None:
    failed = google_route(confidence="unknown", minutes=None)
    live_message = "路线查询失败或达到调用上限，无法确认耗时"
    assert ("unknown", "route_duration", live_message) in route_report(failed)
    assert ("unknown", "route_duration", "自制路段表未覆盖此路线") in route_report(
        failed, "fixture"
    )


def test_successful_live_route_is_not_flagged_route_estimate_but_offline_is() -> None:
    live = route_report(google_route())
    assert not any(code == "route_estimate" for _, code, _ in live)
    assert any(code == "route_live" and status == "verified" for status, code, _ in live)
    offline = route_report(google_route(), "fixture")
    assert any(code == "route_estimate" and status == "unknown" for status, code, _ in offline)


def test_walking_fare_is_zero_but_transit_without_fare_stays_unknown() -> None:
    assert not any(code == "route_fare" for _, code, _ in route_report(google_route()))
    transit = route_report(google_route(transport="transit"), transport="transit")
    assert any(code == "route_fare" and status == "unknown" for status, code, _ in transit)


def test_item_note_is_limited_to_80_characters() -> None:
    def make(note: str | None = None) -> ProposedItem:
        return ProposedItem(
            place_evidence_id=uuid4(), start=NOW, end=NOW + timedelta(hours=1), note=note
        )

    assert make("字" * 80).note == "字" * 80
    assert make().note is None
    with pytest.raises(ValidationError):
        make("字" * 81)


def test_item_note_flows_into_plan_item() -> None:
    from backend.domain.plans import PlanItem

    item = ProposedItem(
        place_evidence_id=uuid4(), start=NOW, end=NOW + timedelta(hours=1), note="枯山水名园"
    )
    assert PlanItem(**item.model_dump()).note == "枯山水名园"
    assert PlanItem(**item.model_dump()).proposed().note == "枯山水名园"


def sightseeing_report(
    count: int,
    pace: str = "",
    category: str = "museum",
    *,
    sourced: bool = True,
    hours: str | None = "24/7",
) -> ValidationReport:
    current = request().model_copy(update={"soft_constraints": (f"节奏：{pace}",) if pace else ()})
    records = tuple(
        record(
            place().model_copy(
                update={
                    "place_id": f"fixture:sight-{i}",
                    "category": category,
                    "opening_hours": hours,
                }
            ),
            current,
        ).model_copy(update={"provider": "test-fixture" if sourced else None})
        for i in range(count)
    )
    start = datetime.fromisoformat("2026-11-03T09:00+09:00")
    proposal = ItineraryProposal(
        expected_revision=1,
        items=tuple(
            ProposedItem(
                place_evidence_id=r.evidence_id,
                start=start + timedelta(hours=i),
                end=start + timedelta(hours=i, minutes=30),
            )
            for i, r in enumerate(records)
        ),
    )
    return validate_itinerary(current, proposal, records, NOW)


@pytest.mark.parametrize(
    ("pace", "count", "warn"),
    [
        ("慢节奏", 3, False),
        ("慢节奏", 4, True),
        ("标准", 5, False),
        ("标准", 8, True),
        ("特种兵", 8, False),
        ("特种兵", 9, True),
        ("", 5, False),
        ("", 8, True),
    ],
)
def test_sightseeing_density_warns_only_above_known_pace_limit(
    pace: str, count: int, warn: bool
) -> None:
    report = sightseeing_report(count, pace)
    warnings = [c for c in report.checks if c.code == "pace_warning"]
    assert bool(warnings) == warn
    assert all(c.status == "unknown" and "提醒" in c.message for c in warnings)
    assert report.status == "partial"


@pytest.mark.parametrize(
    "category",
    [
        "hotel",
        "lodging",
        "hostel",
        "restaurant",
        "cafe",
        "train_station",
        "transit_station",
        "unknown",
    ],
)
def test_non_sightseeing_places_never_inflate_daily_density(category: str) -> None:
    assert not any(
        c.code == "pace_warning" for c in sightseeing_report(9, "慢节奏", category).checks
    )


def test_unsourced_places_cannot_prove_sightseeing_density() -> None:
    assert not any(
        c.code == "pace_warning" for c in sightseeing_report(9, "慢节奏", sourced=False).checks
    )


@pytest.mark.parametrize(
    ("category", "warn"),
    [("museum", True), ("hotel", False), ("restaurant", False), ("train_station", False)],
)
def test_repeated_place_entity_across_days_is_a_warning_even_with_distinct_evidence(
    category: str, warn: bool
) -> None:
    records = tuple(
        record(place().model_copy(update={"category": category, "opening_hours": "24/7"}))
        for _ in range(3)
    )
    assert len({r.evidence_id for r in records}) == 3 and len({r.entity_id for r in records}) == 1
    proposal = ItineraryProposal(
        expected_revision=1,
        items=tuple(
            item(r, f"2026-11-0{3 + i}T10:00+09:00", f"2026-11-0{3 + i}T11:00+09:00")
            for i, r in enumerate(records)
        ),
    )
    report = validate_itinerary(request(), proposal, records, NOW)
    repeated = [c for c in report.checks if c.code == "repeated_place_warning"]
    assert bool(repeated) == warn and report.status == "partial"
    if warn:
        assert len(repeated) == 1 and repeated[0].status == "unknown"
        assert "3次" in repeated[0].message and "2026-11-05" in repeated[0].message


def test_density_groups_by_japan_day_and_does_not_mutate_proposal() -> None:
    current = request().model_copy(update={"soft_constraints": ("节奏：慢节奏",)})
    records = tuple(
        record(place().model_copy(update={"place_id": f"fixture:jst-{i}", "opening_hours": "24/7"}))
        for i in range(6)
    )
    starts = [datetime(2026, 11, 3, hour, tzinfo=UTC) for hour in (6, 7, 8, 18, 19, 20)]
    proposal = ItineraryProposal(
        expected_revision=1,
        items=tuple(
            ProposedItem(
                place_evidence_id=r.evidence_id, start=start, end=start + timedelta(minutes=30)
            )
            for r, start in zip(records, starts, strict=True)
        ),
    )
    before = proposal.model_dump(mode="json")
    report = validate_itinerary(current, proposal, records, NOW)
    assert not any(c.code in ("pace_warning", "repeated_place_warning") for c in report.checks)
    assert proposal.model_dump(mode="json") == before and current.soft_constraints == (
        "节奏：慢节奏",
    )


def test_global_warnings_reach_bounded_feedback_even_when_opening_hours_are_unknown() -> None:
    report = sightseeing_report(8, "标准", hours=None)
    feedback = report.feedback()
    checks = feedback["checks"]
    assert isinstance(checks, list) and len(checks) == 12 and feedback["truncated"]
    assert any(c["code"] == "pace_warning" for c in checks)
    assert all(c["status"] != "conflict" for c in checks)


@pytest.mark.parametrize(
    "category", ["coffee_shop", "bed_and_breakfast", "apartment", "ferry_terminal"]
)
def test_other_known_non_sightseeing_categories_do_not_count(category: str) -> None:
    assert not any(
        c.code == "pace_warning" for c in sightseeing_report(9, "慢节奏", category).checks
    )
    repeated = record(place().model_copy(update={"category": category, "opening_hours": "24/7"}))
    proposal = ItineraryProposal(
        expected_revision=1,
        items=(
            item(repeated),
            item(repeated, "2026-11-04T10:00+09:00", "2026-11-04T11:00+09:00"),
        ),
    )
    report = validate_itinerary(request(), proposal, (repeated,), NOW)
    assert not any(c.code == "repeated_place_warning" for c in report.checks)


def test_hard_conflicts_stay_first_when_global_warnings_are_prioritized() -> None:
    report = sightseeing_report(8, "标准", hours="Mo-Su 08:00-09:00")
    feedback = report.feedback()
    checks = feedback["checks"]
    assert isinstance(checks, list) and report.status == "conflict"
    assert all(c["status"] == "conflict" for c in checks[:8])
    assert any(c["code"] == "pace_warning" and c["status"] == "unknown" for c in checks[8:])

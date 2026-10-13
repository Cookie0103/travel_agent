"""预算诊断只使用完整真实总价，逐档判断不发请求。"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from backend.domain.hotel_recovery import HotelSearchDiagnostics, evaluate, nightly_upper
from backend.domain.itinerary import ItineraryProposal
from backend.domain.travel_request import TravelRequest
from backend.domain.validator import validate_itinerary
from backend.tools.contracts import RESULT_LIMIT, ToolResult
from backend.tools.travel import bounded_offers
from tests.test_hotels import offer, request
from tests.test_itinerary import item, place, record
from tests.test_multi_city_itinerary import multi_city_example


def budget_request(upper: str | None = "10000", basis: str = "per_room_night") -> TravelRequest:
    return TravelRequest.model_validate(
        {
            **request().model_dump(),
            "lodging_budget": {
                "currency": "JPY",
                "basis": basis,
                "amount": {"upper": upper, "lower": "1000"},
            },
        }
    )


@pytest.mark.parametrize("amount,tier", [("72000", "1.5"), ("110000", "2"), ("170000", "3")])
def test_first_nonempty_tier_uses_full_room_night_total(amount: str, tier: str) -> None:
    candidate = offer().model_copy(update={"data_mode": "live", "included_total": Decimal(amount)})
    diagnosis = HotelSearchDiagnostics(steps=["price_sorted_requery"])
    selected = evaluate((candidate,), budget_request(), diagnosis, limit=5)
    assert selected == (candidate,) and diagnosis.tier == Decimal(tier)
    assert diagnosis.original_upper == Decimal("10000")
    assert diagnosis.applied_upper == Decimal("10000") * Decimal(tier)
    assert diagnosis.cause == "budget"
    assert diagnosis.steps[-1] == "tier_" + tier


def test_budget_filter_precedes_truncation_and_coverage_does_not_relax() -> None:
    costly = offer().model_copy(update={"data_mode": "live", "included_total": Decimal("90000")})
    cheap = offer().model_copy(update={"data_mode": "live", "included_total": Decimal("50000")})
    diagnosis = HotelSearchDiagnostics(steps=["price_sorted_requery"])
    assert evaluate((costly, cheap), budget_request(), diagnosis, limit=1) == (cheap,)
    assert diagnosis.in_budget == 1 and diagnosis.over_budget == 1
    assert diagnosis.cause == "coverage" and diagnosis.tier is None


def test_unknown_lower_only_and_empty_never_fabricate_relaxation() -> None:
    unknown = offer().model_copy(update={"data_mode": "live", "included_total": None})
    diagnosis = HotelSearchDiagnostics(steps=["price_sorted_requery"])
    assert evaluate((unknown,), budget_request(), diagnosis, limit=5) == (unknown,)
    assert diagnosis.tier is None and diagnosis.in_budget == 0
    assert diagnosis.cause == "unknown_prices"
    lower = HotelSearchDiagnostics()
    evaluate((offer(),), budget_request(None), lower, limit=5)
    assert lower.tier is None and nightly_upper(budget_request(None)) is None
    empty = HotelSearchDiagnostics()
    assert evaluate((), budget_request(), empty, limit=5) == ()
    assert empty.cause == "upstream_empty"


def test_total_budget_is_normalized_using_whole_trip_rooms_and_nights() -> None:
    assert nightly_upper(budget_request("60000", "total")) == Decimal("10000")
    assert (
        nightly_upper(budget_request("60000", "total").model_copy(update={"rooms": None})) is None
    )


def test_over_budget_cannot_be_planned_before_acceptance() -> None:
    current, proposal, records = multi_city_example()
    current = TravelRequest.model_validate(
        {
            **current.model_dump(),
            "lodging_budget": {
                "amount": {"upper": "1000"},
                "basis": "per_room_night",
                "currency": "JPY",
            },
        }
    )
    report = validate_itinerary(current, proposal, records, datetime.now(UTC))
    assert report.status == "conflict"
    assert any(c.code == "hotel_over_budget_unaccepted" for c in report.checks)


def test_total_budget_cannot_be_reused_in_full_for_each_segment() -> None:
    current, proposal, records = multi_city_example()
    current = TravelRequest.model_validate(
        {
            **current.model_dump(),
            "lodging_budget": {"amount": {"upper": "20000"}, "basis": "total", "currency": "JPY"},
        }
    )
    report = validate_itinerary(current, proposal, records, datetime.now(UTC))
    assert report.status == "conflict"
    assert len([c for c in report.checks if c.code == "hotel_over_budget_unaccepted"]) == 2


def test_single_city_legacy_hotel_reference_cannot_bypass_budget() -> None:
    current = budget_request("1000")
    destination, hotel = record(place(), current), record(offer(), current)
    proposal = ItineraryProposal(
        expected_revision=current.revision,
        items=(item(destination, "2026-11-06T10:00+09:00", "2026-11-06T11:00+09:00"),),
        hotel_evidence_id=hotel.evidence_id,
    )
    report = validate_itinerary(current, proposal, (destination, hotel), datetime.now(UTC))
    assert report.status == "conflict"
    assert any(c.code == "hotel_over_budget_unaccepted" for c in report.checks)


def test_search_size_includes_diagnosis_and_choice_envelope() -> None:
    offers: list[dict[str, object]] = [
        {
            "offer_id": str(uuid4()),
            "evidence_id": str(uuid4()),
            "hotel_name": "合成酒店",
            "booking_url": "https://example.test/" + "x" * 2300,
        }
        for _ in range(5)
    ]
    metadata: dict[str, object] = {
        "relaxation": {"message": "合成诊断" * 200},
        "choice": {"question": "合成确认" * 100},
    }
    kept, trimmed = bounded_offers(offers, (), metadata=metadata)
    assert trimmed and kept
    assert (
        len(
            json.dumps(
                ToolResult(
                    {"offers": kept, **metadata},
                    evidence_ids=tuple(str(o["evidence_id"]) for o in kept),
                ).payload(),
                ensure_ascii=False,
            )
        )
        <= RESULT_LIMIT - 600
    )

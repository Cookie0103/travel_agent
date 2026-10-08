"""酒店金额与比较纯规则：日期/入住口径一致才比较，缺税费不宣称最低价。"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from backend.domain.hotels import HotelOffer, compare, quote
from backend.domain.travel_request import TravelRequest
from backend.providers.hotel_fixture import load_rates


def request() -> TravelRequest:
    return TravelRequest(
        city="京都",
        start_date=date(2026, 11, 6),
        end_date=date(2026, 11, 9),
        adults=2,
        child_ages=(),
        rooms=2,
        budget=Decimal("50000"),
        revision=1,
    )


def offer() -> HotelOffer:
    rates, _ = load_rates()
    value = quote(rates[0], request(), datetime.now(UTC))
    assert value is not None
    return value


def test_fixture_has_six_fictional_hotels_and_twelve_distinct_rates() -> None:
    rates, version = load_rates()
    assert len(rates) >= 12 and len({rate.hotel_id for rate in rates}) == 6
    assert len(version) == 64 and all("模拟" in rate.hotel_name for rate in rates)
    assert any(rate.tax_per_room_night is None for rate in rates)
    assert any(rate.fee_per_room_night is None for rate in rates)


def test_quote_counts_room_nights_weekends_and_decimal_tax() -> None:
    result = offer()
    assert result.base_amount == Decimal("45000")  # 6500*3*2 + 1500*2*2
    assert result.tax_amount == Decimal("4800") and result.fee_amount == Decimal("1200")
    assert result.total == Decimal("51000")
    assert result.card()["lodging_exceeds_trip_budget"] is True
    assert result.expires_at - result.quoted_at == timedelta(minutes=5)


@pytest.mark.parametrize("field", ["tax_amount", "fee_amount"])
def test_missing_component_prevents_total_and_cheapest_claim(field: str) -> None:
    complete = offer()
    incomplete = complete.model_copy(update={field: None})
    comparison = compare((complete, incomplete), datetime.now(UTC))
    assert incomplete.total is None and incomplete.card()["lodging_exceeds_trip_budget"] is None
    assert comparison["comparable"] is False and comparison["lowest_offer_ids"] == []


@pytest.mark.parametrize("change", ["dates", "people", "rooms", "currency", "expired"])
def test_different_scope_or_expiry_cannot_be_ranked(change: str) -> None:
    first = offer()
    if change == "currency":
        second = first.model_copy(update={"currency": "USD"})
    elif change == "expired":
        second = first.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    else:
        changes: dict[str, object] = {
            "dates": {"start_date": date(2026, 11, 7)},
            "people": {"child_ages": (4,)},
            "rooms": {"rooms": 1},
        }
        update = changes[change]
        assert isinstance(update, dict)
        second = first.model_copy(update={"request": first.request.model_copy(update=update)})
    assert compare((first, second), datetime.now(UTC))["comparable"] is False


def test_missing_children_rejected_and_capacity_or_date_window_returns_empty() -> None:
    rates, _ = load_rates()
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="不完整"):
        quote(rates[0], request().model_copy(update={"child_ages": None}), now)
    assert quote(rates[0], request().model_copy(update={"adults": 5}), now) is None
    assert quote(rates[0], request().model_copy(update={"end_date": date(2031, 1, 1)}), now) is None


def test_comparison_keeps_refund_breakfast_distinct_and_handles_ties() -> None:
    first = offer()
    second = first.model_copy(update={"offer_id": uuid4(), "breakfast": True, "refundable": True})
    result = compare((first, second), datetime.now(UTC))
    assert result["comparable"] is True
    assert first.card()["breakfast"] is False and second.card()["breakfast"] is True
    assert result["lowest_offer_ids"] == [str(first.offer_id), str(second.offer_id)]


def test_lodging_limit_uses_current_sub_budget_not_trip_total_or_lower_bound() -> None:
    current = request().model_copy(update={"budget": Decimal("80000")})
    current = TravelRequest.model_validate(
        {
            **current.model_dump(),
            "lodging_budget": {
                "amount": {"upper": "8000"},
                "basis": "per_room_night",
                "currency": "JPY",
            },
        }
    )
    quoted = offer()
    assert quoted.card(current)["lodging_exceeds_lodging_budget"] is True
    assert quoted.card(current)["lodging_exceeds_trip_budget"] is False
    cheap = quoted.model_copy(
        update={
            "base_amount": Decimal("1000"),
            "tax_amount": Decimal("0"),
            "fee_amount": Decimal("0"),
        }
    )
    assert cheap.card(current)["lodging_exceeds_lodging_budget"] is False
    unknown = TravelRequest.model_validate(
        {
            **current.model_dump(),
            "lodging_budget": {
                "amount": {"lower": "8000"},
                "basis": "per_room_night",
                "currency": "JPY",
            },
        }
    )
    assert cheap.card(unknown)["lodging_exceeds_lodging_budget"] is None
    foreign = TravelRequest.model_validate(
        {
            **current.model_dump(),
            "lodging_budget": {"amount": {"upper": "8000"}, "basis": "total", "currency": "USD"},
        }
    )
    assert cheap.card(foreign)["lodging_exceeds_lodging_budget"] is None

"""D6：用户预算事实保留，住宿端点换算与关系现算，不换汇或猜数量。"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.domain.itinerary import ItineraryProposal, ProposedItem
from backend.domain.travel_request import TravelRequest, lodging_budget_relation
from backend.domain.validator import budget_checks


def request(**changes: object) -> TravelRequest:
    data: dict[str, object] = {
        "budget": "50000",
        "start_date": "2026-11-03",
        "end_date": "2026-11-05",
        "rooms": 1,
        "lodging_budget": {
            "amount": {"lower": "30000", "upper": "30000"},
            "basis": "per_room_night",
            "currency": "JPY",
        },
    }
    return TravelRequest.model_validate({**data, **changes})


@pytest.mark.parametrize(
    ("lower", "upper", "status"),
    [
        ("30000", "30000", "conflict"),
        ("20000", "30000", "warning"),
        ("20000", "25000", "within"),
        (None, "30000", "warning"),
        ("20000", None, "unknown"),
        ("30000", None, "conflict"),
    ],
)
def test_endpoint_relationship_after_room_nights_conversion(
    lower: str | None, upper: str | None, status: str
) -> None:
    current = request(
        lodging_budget={
            "amount": {"lower": lower, "upper": upper},
            "basis": "per_room_night",
            "currency": "JPY",
        }
    )
    relation = lodging_budget_relation(current)
    assert relation.status == status
    assert relation.total_lower == (Decimal(lower) * 2 if lower else None)
    assert relation.total_upper == (Decimal(upper) * 2 if upper else None)
    assert current.budget == Decimal("50000")
    assert "budget_relation" not in current.model_dump()


@pytest.mark.parametrize(
    "changes",
    [
        {"rooms": None},
        {"end_date": None},
        {"budget": None},
        {"lodging_budget": None},
        {
            "lodging_budget": {
                "amount": {"lower": "30000", "upper": "30000"},
                "basis": "per_room_night",
                "currency": "USD",
            }
        },
    ],
)
def test_unknown_does_not_guess_or_convert_currency(changes: dict[str, object]) -> None:
    assert lodging_budget_relation(request(**changes)).status == "unknown"


def test_total_basis_needs_no_room_nights_and_boundaries_are_decimal() -> None:
    current = request(
        rooms=None,
        start_date=None,
        end_date=None,
        lodging_budget={"amount": {"upper": "50000.00"}, "basis": "total", "currency": "JPY"},
    )
    assert lodging_budget_relation(current).status == "within"
    assert lodging_budget_relation(request(end_date="2026-11-03")).total_lower == 0
    assert request(budget="60000", lodging_budget=None).lodging_budget is None


@pytest.mark.parametrize(
    "amount",
    [{}, {"lower": "0"}, {"upper": "-1"}, {"lower": "3", "upper": "2"}, {"upper": "1.001"}],
)
def test_rejects_invalid_structure_without_rejecting_business_conflict(
    amount: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        request(lodging_budget={"amount": amount, "basis": "total", "currency": "JPY"})
    assert lodging_budget_relation(request()).status == "conflict"


@pytest.mark.parametrize(
    ("lower", "upper", "status", "check_status"),
    [
        ("30000", "30000", "conflict", "conflict"),
        ("20000", "30000", "warning", "unknown"),
        ("20000", None, "unknown", "unknown"),
    ],
)
def test_validator_reuses_same_relation_with_existing_check_statuses(
    lower: str, upper: str | None, status: str, check_status: str
) -> None:
    current = request(
        lodging_budget={
            "amount": {"lower": lower, "upper": upper},
            "basis": "per_room_night",
            "currency": "JPY",
        }
    )
    proposal = ItineraryProposal(
        expected_revision=0,
        items=(
            ProposedItem(
                place_evidence_id=uuid4(),
                start=datetime.fromisoformat("2026-11-03T10:00+09:00"),
                end=datetime.fromisoformat("2026-11-03T11:00+09:00"),
            ),
        ),
    )
    _, _, checks = budget_checks(current, proposal, {}, datetime.now(UTC))
    entry = next(c for c in checks if c.code == f"lodging_budget_{status}")
    assert entry.status == check_status

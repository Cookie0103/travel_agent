"""R04/R05：条件更新只改指定字段；证据必须匹配当前版本、条件和有效期。"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.domain.evidence import EvidenceKind, EvidenceRecord, evidence_conditions
from backend.domain.travel_request import (
    RequestConflict,
    RequestPatch,
    TravelRequest,
    apply_request_patch,
    invalidated_kinds,
)


def test_patch_preserves_unmentioned_fields_and_clear_is_explicit() -> None:
    """R04：解释/无变化不加版本，未指定字段保留，clear显式清除。"""
    current = TravelRequest(city="京都", adults=2, budget=Decimal("50000"), revision=3)
    updated, changed = apply_request_patch(
        current,
        RequestPatch.model_validate(
            {"expected_revision": 3, "set": {"rooms": 1}, "clear": ["budget"]}
        ),
    )
    assert (updated.city, updated.adults, updated.budget, updated.rooms) == ("京都", 2, None, 1)
    assert updated.revision == 4 and changed == {"budget", "rooms"}
    same, changed = apply_request_patch(
        updated, RequestPatch.model_validate({"expected_revision": 4, "set": {"adults": 2}})
    )
    assert same == updated and not changed
    with pytest.raises(RequestConflict):
        apply_request_patch(updated, RequestPatch(expected_revision=3))


@pytest.mark.parametrize(
    "values",
    [
        {"set": {"adults": None}},
        {"set": {"user_id": "forged"}},
        {"set": {"adults": 2}, "clear": ["adults"]},
        {"clear": ["revision"]},
        {"set": {"child_ages": [18]}},
        {"set": {"adults": True}},
        {"set": {"start_date": "2026-10-08", "end_date": "2026-10-07"}},
    ],
)
def test_invalid_patch_is_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RequestPatch.model_validate({"expected_revision": 0, **values})


def test_hotel_requires_explicit_children_information() -> None:
    request = TravelRequest.model_validate(
        {
            "city": "京都",
            "start_date": "2026-10-08",
            "end_date": "2026-10-10",
            "adults": 2,
            "rooms": 1,
        }
    )
    assert request.hotel_requirements() == ("child_ages",)
    assert not request.model_copy(update={"child_ages": ()}).hotel_requirements()
    assert invalidated_kinds(frozenset({"start_date"})) == {"hotel_offer", "route"}
    assert invalidated_kinds(frozenset({"transport"})) == {"route"}


def test_same_day_travel_is_valid_but_hotel_requires_overnight() -> None:
    request = TravelRequest.model_validate(
        {
            "city": "京都",
            "start_date": "2026-10-08",
            "end_date": "2026-10-08",
            "adults": 2,
            "rooms": 1,
            "child_ages": [],
        }
    )
    assert request.start_date == request.end_date
    assert request.hotel_requirements() == ("overnight_stay",)


def test_evidence_missing_source_is_unknown_and_wrong_conditions_rejected() -> None:
    """R05：来源缺失不能当确定事实；同版本也必须核对适用日期/人数。"""
    now = datetime.now(UTC)
    request = TravelRequest(city="京都", revision=2)
    record = EvidenceRecord(
        entity_id="offer:1",
        field_path="total",
        value="5000.00",
        kind="hotel_offer",
        request_revision=2,
        conditions=evidence_conditions(request, "hotel_offer"),
        retrieved_at=now,
        valid_until=now + timedelta(minutes=5),
        data_mode="fixture",
    )
    assert record.status == "unknown" and record.applicable(request, now)
    assert not record.applicable(request.model_copy(update={"adults": 2}), now)
    assert record.applicable(request.model_copy(update={"revision": 3}), now)
    assert not record.applicable(request, now + timedelta(minutes=5))


def _record(request: TravelRequest, kind: EvidenceKind, now: datetime) -> EvidenceRecord:
    return EvidenceRecord(
        entity_id="x:1",
        field_path="value",
        value="v",
        kind=kind,
        request_revision=request.revision,
        conditions=evidence_conditions(request, kind),
        retrieved_at=now,
        valid_until=now + timedelta(minutes=5),
        data_mode="fixture",
    )


@pytest.mark.parametrize("kind", ["place", "article"])
def test_place_and_article_evidence_survive_revision_bump_but_not_city_or_expiry(
    kind: EvidenceKind,
) -> None:
    now = datetime.now(UTC)
    request = TravelRequest(city="京都", revision=2)
    record = _record(request, kind, now)
    later = request.model_copy(update={"revision": 5, "adults": 2})
    assert record.applicable(later, now)
    assert not record.applicable(later.model_copy(update={"city": "大阪"}), now)
    assert not record.applicable(later, now + timedelta(minutes=5))


@pytest.mark.parametrize("kind", ["hotel_offer", "route"])
def test_hotel_and_route_evidence_no_longer_bound_to_revision(kind: EvidenceKind) -> None:
    now = datetime.now(UTC)
    request = TravelRequest(city="京都", revision=2)
    record = _record(request, kind, now)
    assert record.applicable(request, now)
    assert record.applicable(request.model_copy(update={"revision": 3}), now)
    assert not record.applicable(request.model_copy(update={"city": "大阪"}), now)


def test_route_and_offer_evidence_survive_unrelated_edits_but_not_their_own_conditions() -> None:
    """revision不再绑定：预算/兴趣变化保留；入住或路线条件变化、过期仍失效。"""
    now = datetime.now(UTC)
    base = TravelRequest(
        city="京都",
        start_date=date(2026, 11, 3),
        end_date=date(2026, 11, 5),
        adults=2,
        child_ages=(),
        rooms=1,
        transport="transit",
        revision=2,
    )
    offer, route = _record(base, "hotel_offer", now), _record(base, "route", now)
    unrelated = base.model_copy(
        update={"budget": Decimal("90000"), "interests": ("寺",), "revision": 7}
    )
    assert offer.applicable(unrelated, now) and route.applicable(unrelated, now)
    changes: tuple[tuple[str, object], ...] = (
        ("start_date", date(2026, 11, 4)),
        ("adults", 3),
        ("rooms", 2),
        ("child_ages", (5,)),
    )
    for field, value in changes:
        changed = base.model_copy(update={field: value})
        assert not offer.applicable(changed, now), field
    route_changes: tuple[tuple[str, object], ...] = (
        ("transport", "taxi"),
        ("departure_time", time(9, 0)),
    )
    for field, value in route_changes:
        changed = base.model_copy(update={field: value})
        assert not route.applicable(changed, now), field
    assert offer.applicable(base.model_copy(update={"transport": "taxi"}), now)  # 报价与交通无关
    assert not route.applicable(base, now + timedelta(minutes=5))

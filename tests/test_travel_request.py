"""R04/R05：条件更新只改指定字段；证据必须匹配当前版本、条件和有效期。"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.domain import travel_request as conditions
from backend.domain.evidence import EvidenceKind, EvidenceRecord, evidence_conditions
from backend.domain.travel_request import (
    RequestConflict,
    RequestPatch,
    TravelRequest,
    apply_request_patch,
    invalidated_kinds,
)


def multi_city_fields() -> dict[str, object]:
    return {
        "city": "大阪",
        "start_date": "2026-11-03",
        "end_date": "2026-11-07",
        "segments": [
            {"city": "大阪", "arrive": "2026-11-03", "depart": "2026-11-05"},
            {"city": "神户", "arrive": "2026-11-05", "depart": "2026-11-07"},
            {"city": "京都", "arrive": "2026-11-07", "depart": "2026-11-07"},
        ],
    }


@pytest.mark.parametrize(
    "segments",
    [
        [{"city": "大阪", "arrive": "2026-11-03", "depart": "2026-11-07"}],
        [
            {"city": "大阪", "arrive": "2026-11-03", "depart": "2026-11-05"},
            {"city": "京都", "arrive": "2026-11-04", "depart": "2026-11-07"},
        ],
        [
            {"city": "大阪", "arrive": "2026-11-03", "depart": "2026-11-05"},
            {"city": "京都", "arrive": "2026-11-06", "depart": "2026-11-07"},
        ],
        [
            {"city": "大阪", "arrive": "2026-11-03", "depart": "2026-11-03"},
            {"city": "京都", "arrive": "2026-11-03", "depart": "2026-11-07"},
        ],
    ],
)
def test_multi_city_segments_reject_single_overlap_gap_and_nonfinal_zero_night(
    segments: list[dict[str, str]],
) -> None:
    """R04：城市段必须连续，至少两段且仅末段允许当日往返。"""
    with pytest.raises(ValidationError):
        TravelRequest.model_validate({**multi_city_fields(), "segments": segments})


@pytest.mark.parametrize(
    "different", [{"city": "京都"}, {"start_date": "2026-11-02"}, {"end_date": "2026-11-08"}]
)
def test_multi_city_rejects_globals_inconsistent_with_segments(different: dict[str, str]) -> None:
    """R04：保留的全局城市/日期必须与城市段首末一致。"""
    with pytest.raises(ValidationError):
        TravelRequest.model_validate({**multi_city_fields(), **different})


@pytest.mark.parametrize("cleared", ["city", "start_date", "end_date"])
def test_segment_patch_cannot_silently_ignore_explicit_global_clear(cleared: str) -> None:
    """R04：派生不能吞掉显式clear或使来源标签与值矛盾。"""
    with pytest.raises(ValidationError):
        RequestPatch.model_validate(
            {
                "expected_revision": 0,
                "set": {"segments": multi_city_fields()["segments"]},
                "clear": [cleared],
            }
        )


def test_segment_patch_derives_globals_preserves_revision_and_explicit_clear() -> None:
    """R04/R05：派生只发生在条件更新；查询副本不改变当前请求。"""
    current = TravelRequest(city="京都", revision=4)
    updated, changed = apply_request_patch(
        current,
        RequestPatch.model_validate(
            {"expected_revision": 4, "set": {"segments": multi_city_fields()["segments"]}}
        ),
    )
    assert (updated.city, updated.start_date, updated.end_date, updated.revision) == (
        "大阪",
        date(2026, 11, 3),
        date(2026, 11, 7),
        5,
    )
    assert changed == {"segments", "city", "start_date", "end_date"}
    assert invalidated_kinds(frozenset({"segments"})) == {"hotel_offer", "route"}
    segments = conditions.trip_segments(updated)
    assert conditions.cities_on(updated, date(2026, 11, 5)) == {"大阪", "神户"}
    assert conditions.cities_on(updated, date(2026, 11, 7)) == {"神户", "京都"}
    local = conditions.segment_request(updated, segments[1])
    assert (local.city, local.start_date, local.end_date, local.segments) == (
        "神户",
        date(2026, 11, 5),
        date(2026, 11, 7),
        None,
    )
    assert updated.city == "大阪" and updated.revision == 5 and current.revision == 4
    same, changed = apply_request_patch(
        updated,
        RequestPatch.model_validate({"expected_revision": 5, "set": {"segments": segments}}),
    )
    assert same == updated and not changed
    cleared, changed = apply_request_patch(
        updated, RequestPatch(expected_revision=5, clear=("segments",))
    )
    assert cleared.segments is None and cleared.city == "大阪" and cleared.revision == 6
    assert changed == {"segments"}


def test_lodging_budget_unlimited_is_strict_and_mutually_exclusive() -> None:
    """R04：不限不是null；不与有金额并存，不接受字符串布尔值。"""
    for fields in (
        {"lodging_budget_unlimited": "true"},
        {
            "lodging_budget_unlimited": True,
            "lodging_budget": {
                "amount": {"upper": "20000"},
                "basis": "per_room_night",
                "currency": "JPY",
            },
        },
    ):
        with pytest.raises(ValidationError):
            RequestPatch.model_validate({"expected_revision": 0, "set": fields})
    request, changed = apply_request_patch(
        TravelRequest(),
        RequestPatch.model_validate(
            {"expected_revision": 0, "set": {"lodging_budget_unlimited": True}}
        ),
    )
    assert request.lodging_budget_unlimited and changed == {"lodging_budget_unlimited"}


def test_explicit_unlimited_false_remains_a_patch_operation() -> None:
    """R04：False必须保留在输入和幂等键中，不能变成空操作。"""
    from backend.persistence.operations import key

    current = TravelRequest(lodging_budget_unlimited=True, revision=1)
    patch = RequestPatch.model_validate(
        {"expected_revision": 1, "set": {"lodging_budget_unlimited": False}}
    )
    assert patch.set_fields.model_dump(exclude_unset=True) == {"lodging_budget_unlimited": False}
    assert key(patch) != key(RequestPatch(expected_revision=1))
    updated, changed = apply_request_patch(current, patch)
    assert not updated.lodging_budget_unlimited and updated.revision == 2
    assert changed == {"lodging_budget_unlimited"}


def test_multi_city_rejects_reverse_dates_and_more_than_six_segments() -> None:
    """R04：宽松业务日期也必须满足结构上限，段内日期不能逆序。"""
    reverse = {"city": "京都", "arrive": "2026-11-05", "depart": "2026-11-04"}
    with pytest.raises(ValidationError):
        conditions.TripSegment.model_validate(reverse)
    seven = [
        {"city": "京都", "arrive": f"2026-11-{i:02}", "depart": f"2026-11-{i + 1:02}"}
        for i in range(3, 10)
    ]
    with pytest.raises(ValidationError):
        RequestPatch.model_validate({"expected_revision": 0, "set": {"segments": seven}})


def test_pace_hard_constraint_takes_priority_and_unknown_text_stays_unknown() -> None:
    request = TravelRequest(hard_constraints=("节奏：轻松",), soft_constraints=("节奏：特种兵",))
    assert conditions.pace_of(request) == "慢节奏"
    assert conditions.pace_of(TravelRequest(soft_constraints=("尽量自在一点",))) is None
    assert conditions.trip_segments(TravelRequest()) == ()


@pytest.mark.parametrize("source", ["soft_constraints", "hard_constraints"])
@pytest.mark.parametrize(
    ("text", "pace"),
    [
        ("轻松", "慢节奏"),
        ("佛系", "慢节奏"),
        ("悠闲", "慢节奏"),
        ("标准节奏", "标准"),
        ("正常", "标准"),
        ("特种兵", "特种兵"),
    ],
)
def test_pace_aliases_share_soft_and_hard_recognition(source: str, text: str, pace: str) -> None:
    assert conditions.pace_of(TravelRequest.model_validate({source: [f"节奏：{text}"]})) == pace


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("神户", "神戸市"),
        ("Kobe", "神戸"),
        (" 大阪市 ", "OSAKA"),
        ("京都", "Kyoto"),
        ("奈良市", "nara"),
    ],
)
def test_same_city_only_normalizes_known_aliases(a: str, b: str) -> None:
    assert conditions.same_city(a, b)
    assert not conditions.same_city(a, "东京")


@pytest.mark.parametrize("location", [None, "京都站"])
def test_single_city_segment_copy_keeps_baseline_evidence_dictionaries(
    location: str | None,
) -> None:
    """R05：新派生入口不得改变旧单城市四种证据条件字典。"""
    current = TravelRequest(
        city="京都",
        start_date=date(2026, 11, 3),
        end_date=date(2026, 11, 5),
        adults=2,
        child_ages=(),
        rooms=1,
        hotel_search_location=location,
        transport="walk",
    )
    local = conditions.segment_request(current, conditions.trip_segments(current)[0])
    expected: dict[EvidenceKind, dict[str, object]] = {
        "place": {"city": "京都"},
        "article": {"city": "京都"},
        "route": {
            "city": "京都",
            "start_date": "2026-11-03",
            "end_date": "2026-11-05",
            "transport": "walk",
            "departure_time": None,
        },
        "hotel_offer": {
            "city": "京都",
            "start_date": "2026-11-03",
            "end_date": "2026-11-05",
            "adults": 2,
            "child_ages": [],
            "rooms": 1,
            "currency": "JPY",
        },
    }
    if location:
        expected["hotel_offer"]["hotel_search_location"] = location
    for kind, values in expected.items():
        assert evidence_conditions(current, kind) == values == evidence_conditions(local, kind)
    assert current == local


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

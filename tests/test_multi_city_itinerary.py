"""R06/R07：合成城市与酒店证据验证分段住宿、按天归属及旧单城报告不变。"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from backend.domain.condition_labels import update_message
from backend.domain.evidence import EvidenceRecord
from backend.domain.hotels import HotelOffer, quote
from backend.domain.itinerary import HotelStay, ItineraryProposal, ValidationReport
from backend.domain.travel_request import TravelRequest, segment_request, trip_segments
from backend.domain.validator import HOTEL_CONDITIONS_REASON, validate_itinerary
from backend.providers.hotel_fixture import load_rates
from tests.test_itinerary import item, place, record, request


def multi_city_example(
    count: int = 5,
    second_city: str = "神户",
) -> tuple[TravelRequest, ItineraryProposal, tuple[EvidenceRecord, ...]]:
    """测试内构造证据，不扩正式景点/酒店目录，不请求真实API。"""
    now = datetime.now(UTC)
    current = TravelRequest.model_validate(
        {
            **request().model_dump(),
            "city": "大阪",
            "end_date": "2026-11-07",
            "budget": "500000",
            "segments": [
                {"city": "大阪", "arrive": "2026-11-03", "depart": "2026-11-05"},
                {"city": second_city, "arrive": "2026-11-05", "depart": "2026-11-07"},
                {"city": "京都", "arrive": "2026-11-07", "depart": "2026-11-07"},
            ],
        }
    )
    per_day = count // 5
    assert count % 5 == 0
    records, items = [], []
    template = place()
    for index in range(count):
        day, position = divmod(index, per_day)
        middle_city = "神戸市" if second_city == "神户" else second_city
        city = "大阪" if day < 2 else middle_city if day < 4 else "Kyoto"
        destination = template.model_copy(
            update={
                "place_id": f"synthetic:multi-city:{index}",
                "city": city,
                "name": f"合成景点{index + 1}",
                "opening_hours": "24/7",
            }
        )
        evidence = record(destination, current).model_copy(
            update={
                "retrieved_at": now - timedelta(seconds=1),
                "valid_until": now + timedelta(hours=1),
            }
        )
        records.append(evidence)
        start = datetime.fromisoformat("2026-11-03T08:00+09:00") + timedelta(
            days=day, hours=position
        )
        items.append(item(evidence, start.isoformat(), (start + timedelta(hours=1)).isoformat()))
    rates, _ = load_rates()
    stays = []
    for segment in trip_segments(current)[:2]:
        scoped = segment_request(current, segment)
        offer = quote(rates[0].model_copy(update={"city": segment.city}), scoped, now)
        assert offer is not None
        evidence = record(offer, scoped).model_copy(
            update={"retrieved_at": now, "valid_until": offer.expires_at}
        )
        records.append(evidence)
        stays.append(
            HotelStay(
                check_in=segment.arrive,
                check_out=segment.depart,
                hotel_evidence_id=evidence.evidence_id,
            )
        )
    return (
        current,
        ItineraryProposal(
            expected_revision=current.revision, items=tuple(items), hotel_stays=tuple(stays)
        ),
        tuple(records),
    )


def test_same_city_return_stays_do_not_count_as_repeated_sightseeing() -> None:
    """R06：同城分两次入住、相同hotel_id仍为合法独立日期报价。"""
    current, proposal, records = multi_city_example(second_city="大阪")
    offers = [HotelOffer.model_validate(r.value) for r in records[-2:]]
    assert offers[0].hotel_id == offers[1].hotel_id
    assert offers[0].request.start_date != offers[1].request.start_date
    report = validate_itinerary(current, proposal, records, datetime.now(UTC))
    assert report.status == "partial"
    assert not any(c.status == "conflict" for c in report.checks)
    assert report.known_cost == Decimal("30000")


def referenced(
    proposal: ItineraryProposal, records: tuple[EvidenceRecord, ...]
) -> tuple[EvidenceRecord, ...]:
    return tuple(record for record in records if record.evidence_id in proposal.evidence_ids())


def test_new_conditions_have_human_readable_update_receipts() -> None:
    """R13：工具回执支持城市段与不限，不暴露模型repr或内部编号。"""
    current, _, _ = multi_city_example()
    current = current.model_copy(update={"lodging_budget_unlimited": True})
    message = update_message(current, ("segments", "lodging_budget_unlimited"), ())
    assert "大阪" in message and "神户" in message and "不限" in message
    assert "TripSegment(" not in message and "True" not in message


def test_switching_unlimited_to_an_amount_does_not_report_budget_unknown() -> None:
    """R13：不限→金额的同一回执必须一致，不能将false显示成预算未知。"""
    current, _, _ = multi_city_example()
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
    message = update_message(current, ("lodging_budget", "lodging_budget_unlimited"), ())
    assert "每晚住宿预算=未知" not in message
    assert "8000" in message and "每房每晚" in message


def test_three_cities_accept_aliases_and_sum_two_hotel_stays() -> None:
    """R06：三个城市和转场日合法，住宿已知成本为两段之和。"""
    current, proposal, records = multi_city_example()
    report = validate_itinerary(current, proposal, records, datetime.now(UTC))
    assert report.status == "partial" and not any(c.status == "conflict" for c in report.checks)
    assert sum(c.code == "hotel_total" for c in report.checks) == 2
    assert report.known_cost == Decimal("30000")
    assert not any(c.code == "hotel_missing" for c in report.checks)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("missing", "hotel_stay_missing"),
        ("scope", "hotel_stay_scope"),
        ("quote", "hotel_stay_scope"),
    ],
)
def test_missing_mismatched_or_other_segment_quote_is_a_hard_conflict(
    fault: str, code: str
) -> None:
    """R06：段范围及报价错配返回机械反馈，不能把任一适用报价随意用于别段。"""
    current, proposal, records = multi_city_example()
    first, second = proposal.hotel_stays
    stays: tuple[HotelStay, ...]
    if fault == "missing":
        stays = (first,)
    elif fault == "scope":
        stays = (first.model_copy(update={"check_out": second.check_out}), second)
    else:
        stays = (first.model_copy(update={"hotel_evidence_id": second.hotel_evidence_id}), second)
    changed = proposal.model_copy(update={"hotel_stays": stays})
    report = validate_itinerary(current, changed, referenced(changed, records), datetime.now(UTC))
    assert report.status == "conflict"
    assert any(c.code == code and c.status == "conflict" for c in report.checks)
    if fault == "quote":
        assert any(HOTEL_CONDITIONS_REASON in c.message for c in report.checks)


def test_unknown_source_quote_still_must_belong_to_its_selected_stay() -> None:
    """R06：来源不完整仍按段核对conditions，不能把第一段报价用于第二段。"""
    current, proposal, records = multi_city_example()
    first, second = proposal.hotel_stays
    second = second.model_copy(update={"hotel_evidence_id": first.hotel_evidence_id})
    proposal = proposal.model_copy(update={"hotel_stays": (first, second)})
    records = tuple(
        r.model_copy(update={"source_ref": None}) if r.kind == "hotel_offer" else r for r in records
    )
    report = validate_itinerary(current, proposal, referenced(proposal, records), datetime.now(UTC))
    assert report.status == "conflict"
    assert any(c.code == "hotel_stay_scope" and c.status == "conflict" for c in report.checks)


def test_transfer_day_allows_both_cities_but_a_different_day_rejects_wrong_city() -> None:
    """R06：转场日含前后城市；非转场日不接受未列出的day trip。"""
    current, proposal, records = multi_city_example()
    first = records[0]
    transfer = proposal.items[0].model_copy(
        update={
            "start": datetime.fromisoformat("2026-11-05T07:00+09:00"),
            "end": datetime.fromisoformat("2026-11-05T08:00+09:00"),
        }
    )
    changed = proposal.model_copy(update={"items": (transfer, *proposal.items[2:])})
    report = validate_itinerary(current, changed, referenced(changed, records), datetime.now(UTC))
    assert not any(c.code == "city" for c in report.checks)
    assert isinstance(first.value, dict)
    wrong = first.model_copy(update={"value": {**first.value, "city": "奈良"}})
    changed_records = tuple(
        wrong if record.evidence_id == first.evidence_id else record for record in records
    )
    report = validate_itinerary(current, proposal, changed_records, datetime.now(UTC))
    assert any(c.code == "city" and c.status == "conflict" for c in report.checks)


def test_nightly_budget_warning_is_advisory_and_unlimited_skips_it() -> None:
    """R06：按各段房晚比较，不用全程晚数稀释报价；明确不限不误报。"""
    current, proposal, records = multi_city_example()
    limited = TravelRequest.model_validate(
        {
            **current.model_dump(),
            "lodging_budget": {
                "amount": {"upper": "1000"},
                "basis": "per_room_night",
                "currency": "JPY",
            },
        }
    )
    report = validate_itinerary(limited, proposal, records, datetime.now(UTC))
    warnings = [c for c in report.checks if c.code == "hotel_over_nightly_budget"]
    assert len(warnings) == 2 and all(c.status == "unknown" for c in warnings)
    assert report.status == "partial" and report.known_cost == Decimal("30000")
    unlimited = current.model_copy(update={"lodging_budget_unlimited": True})
    report = validate_itinerary(unlimited, proposal, records, datetime.now(UTC))
    assert not any(c.code == "hotel_over_nightly_budget" for c in report.checks)


def test_segment_hotel_card_uses_its_own_nights_for_budget_warning() -> None:
    """R05/R06：两晚7500/晚超过6000，不能用全程四晚预算误报未超。"""
    current, _, records = multi_city_example()
    limited = TravelRequest.model_validate(
        {
            **current.model_dump(),
            "lodging_budget": {
                "amount": {"upper": "6000"},
                "basis": "per_room_night",
                "currency": "JPY",
            },
        }
    )
    for evidence in records[-2:]:
        assert (
            HotelOffer.model_validate(evidence.value).card(limited)[
                "lodging_exceeds_lodging_budget"
            ]
            is True
        )


def test_single_city_validation_report_matches_the_pre_segment_baseline() -> None:
    """R06：空segments的完整报告（含文案/顺序/金额）保持基线，不只比较状态。"""
    destination = record(place().model_copy(update={"opening_hours": "24/7"}))
    proposal = ItineraryProposal(expected_revision=1, items=(item(destination),))
    actual = validate_itinerary(request(), proposal, (destination,), datetime.now(UTC))
    expected = ValidationReport.model_validate(
        {
            "status": "partial",
            "known_cost": "0",
            "estimated_cost": "0",
            "checks": [
                {
                    "subject": "item:0",
                    "status": "verified",
                    "code": "trip_dates",
                    "message": "停留日期符合旅行范围",
                },
                {
                    "subject": "item:0",
                    "status": "verified",
                    "code": "opening_hours",
                    "message": "快照营业时间覆盖整段停留",
                },
                {
                    "subject": "budget",
                    "status": "unknown",
                    "code": "other_costs",
                    "message": "景点门票、餐饮等未获得完整费用证据，不能认定全程预算满足",
                },
                {
                    "subject": "lodging_budget",
                    "status": "unknown",
                    "code": "lodging_budget_unknown",
                    "message": "住宿预算未知；不会按全程预算自动分配。",
                },
                {
                    "subject": "hotel",
                    "status": "unknown",
                    "code": "hotel_missing",
                    "message": "未选择住宿报价，不猜测住宿费用",
                },
            ],
        }
    )
    assert actual.model_dump_json() == expected.model_dump_json()

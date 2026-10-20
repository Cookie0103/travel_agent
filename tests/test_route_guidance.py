"""路段冲突的可执行提示与TRACE标签：规则不变，只验证文案和安全诊断。"""

from datetime import datetime

from backend.domain.evidence import EvidenceRecord
from backend.domain.itinerary import ItineraryProposal, ProposedItem, ValidationReport
from backend.domain.validator import validate_itinerary
from backend.providers.routes_fixture import estimate, load_routes
from backend.tools.travel import DEFINITIONS, report_detail
from tests.test_itinerary import NOW, item, place, record, request

SECRET = "SECRETNAME"


def route_record(first: EvidenceRecord, second: EvidenceRecord, departure: str) -> EvidenceRecord:
    rates, _ = load_routes()
    route = estimate(
        rates, request(), first.entity_id, second.entity_id, datetime.fromisoformat(departure)
    )
    return record(route)


def two_day(
    d1: str, d2: str, first_item_route: bool = True
) -> tuple[ItineraryProposal, tuple[EvidenceRecord, ...]]:
    a, b = record(place()), record(place("osm:way/314446153"))
    r1, r2 = route_record(a, b, d1), route_record(a, b, d2)
    items: tuple[ProposedItem, ...] = (
        item(a, "2026-11-03T10:00+09:00", "2026-11-03T11:00+09:00"),
        item(b, "2026-11-03T12:00+09:00", "2026-11-03T13:00+09:00", r1),
        item(
            a,
            "2026-11-04T10:00+09:00",
            "2026-11-04T11:00+09:00",
            r1 if first_item_route else None,
        ),
        item(b, "2026-11-04T12:00+09:00", "2026-11-04T13:00+09:00", r2),
    )
    return ItineraryProposal(expected_revision=1, items=items), (a, b, r1, r2)


def route_checks(report: ValidationReport) -> dict[str, tuple[str, str]]:
    return {c.subject: (c.code, c.message) for c in report.checks if c.subject.startswith("route")}


def test_default_departures_give_concrete_fix_messages_and_unchanged_codes() -> None:
    # 00:00Z == 09:00 JST：时区感知时刻必须按京都时间显示
    proposal, records = two_day("2026-11-03T00:00+00:00", "2026-11-04T06:00+09:00")
    report = validate_itinerary(request(), proposal, records, NOW)
    found = route_checks(report)
    code, message = found["route:0->1"]
    assert code == "route_departure"
    assert (
        "09:00" in message
        and "11:00" in message
        and "用11:00作为出发时间重新estimate_routes" in message
    )
    code, message = found["route:2->3"]
    assert code == "route_departure"
    assert "路段出发(06:00)早于前一项结束(11:00)" in message
    assert report.status == "conflict"


def test_late_departure_message_names_latest_allowed_time() -> None:
    proposal, records = two_day("2026-11-03T11:00+09:00", "2026-11-04T15:00+09:00")
    found = route_checks(validate_itinerary(request(), proposal, records, NOW))
    code, message = found["route:2->3"]
    assert code == "route_departure"
    assert "路段出发(15:00)晚于下一项开始(12:00)" in message and "不晚于12:00" in message


def test_first_item_of_day_with_route_gets_remedy() -> None:
    proposal, records = two_day("2026-11-03T11:00+09:00", "2026-11-04T11:00+09:00")
    found = route_checks(validate_itinerary(request(), proposal, records, NOW))
    code, message = found["route:1->2"]
    assert code == "route_unexpected" and "请去掉该项的route_evidence_id" in message


def test_departure_at_previous_end_is_still_clean() -> None:
    proposal, records = two_day("2026-11-03T11:00+09:00", "2026-11-04T11:00+09:00", False)
    report = validate_itinerary(request(), proposal, records, NOW)
    assert not [
        c for c in report.checks if c.subject.startswith("route") and c.status == "conflict"
    ]
    assert all(c.code != "route_departure" for c in report.checks)


def test_trace_labels_carry_positions_and_times_but_no_names() -> None:
    proposal, records = two_day("2026-11-03T09:00+09:00", "2026-11-04T15:00+09:00")
    renamed = tuple(
        r.model_copy(update={"source_ref": SECRET, "entity_id": r.entity_id}) for r in records
    )
    report = validate_itinerary(request(), proposal, renamed, NOW)
    poisoned = ValidationReport(
        status=report.status,
        checks=tuple(
            c.model_copy(update={"subject": SECRET, "message": SECRET}) for c in report.checks
        ),
        known_cost=report.known_cost,
        estimated_cost=report.estimated_cost,
    )
    for source in (report, poisoned):
        detail = report_detail(source)
        assert all(len(label) <= 60 for label in detail)
        assert SECRET not in "".join(detail)
    labels = report_detail(report)
    assert "route_departure:conflict@d1i2 dep=09:00 pe=11:00 ns=12:00" in labels
    assert "route_departure:conflict@d2i2 dep=15:00 pe=11:00 ns=12:00" in labels
    assert "route_unexpected:conflict@d2i1" in labels


def test_estimate_routes_description_has_departure_guidance() -> None:
    text = next(d.description for d in DEFINITIONS if d.name == "estimate_routes")
    for phrase in ("前一项结束时间", "每天首项不接路段", "最多6段", "重新估算"):
        assert phrase in text

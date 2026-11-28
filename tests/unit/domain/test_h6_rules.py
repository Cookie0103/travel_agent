"""复核后的三条业务规则，使用现有离线行程和来源夹具。"""

from datetime import date, timedelta

import pytest

from backend.domain.itinerary import ItineraryProposal
from backend.domain.itinerary_revision import edit_scope_check
from backend.domain.validator import validate_itinerary
from eval.v3.score import auto_validator_results, rule_gate
from tests.unit.domain.test_itinerary import NOW, item, place, record, request


@pytest.mark.parametrize(
    "delay_minutes,expected", [(30, "verified"), (-1, "conflict")], ids=("delay30", "advance1")
)
def test_edit_scope_preserves_note_changes_with_valid_same_slot_delays(
    delay_minutes: int, expected: str
) -> None:
    current = request()
    destination = place()
    evidence = record(destination, current)
    first = item(evidence, "2026-11-03T09:00+09:00", "2026-11-03T10:00+09:00")
    second = item(evidence, "2026-11-04T14:00+09:00", "2026-11-04T15:00+09:00")
    original = ItineraryProposal(expected_revision=current.revision, items=(first, second))
    delay = timedelta(minutes=delay_minutes)
    changed = first.model_copy(
        update={
            "start": first.start + delay,
            "end": first.end + delay,
            "note": "补充地点介绍",
        }
    )
    revised = original.model_copy(update={"items": (changed, second)})
    check = edit_scope_check(
        "只改第二天下午", current, original, revised, {evidence.evidence_id: destination}
    )
    assert check is not None and check.status == expected


def test_rain_plan_is_advisory_without_a_hard_requirement() -> None:
    current = request()
    park = place().model_copy(update={"category": "park", "indoor": False})
    evidence = record(park, current)
    draft = ItineraryProposal(expected_revision=current.revision, items=(item(evidence),))
    weather = {(park.city, date(2026, 11, 3)): 60}
    report = validate_itinerary(current, draft, (evidence,), NOW, weather=weather)
    rain = next(check for check in report.checks if check.code == "rain_plan")
    assert rain.status == "unknown"
    checks = [rain.model_dump()]
    assert rule_gate(checks)["passed"] is True
    assert auto_validator_results(checks)[0].tier == "soft"


@pytest.mark.parametrize(
    "name,expected",
    [("知らない小径", "unknown"), ("桂離宮　Ａ棟", "verified")],
)
def test_must_visit_checks_unknown_and_name_normalization(name: str, expected: str) -> None:
    current = request().model_copy(
        update={"hard_constraints": (f"必須去：{name}", f"必须去：{name}")}
    )
    destination = place().model_copy(update={"name": "桂离宫 A栋"})
    evidence = record(destination, current)
    draft = ItineraryProposal(expected_revision=current.revision, items=(item(evidence),))
    result = validate_itinerary(current, draft, (evidence,), NOW)
    assert [check.status for check in result.checks if check.code == "must_visit"] == [expected]


def test_rain_plan_is_hard_when_user_requires_an_indoor_fallback() -> None:
    current = request().model_copy(update={"hard_constraints": ("下雨时请保留室內備選",)})
    park = place().model_copy(update={"category": "park", "indoor": False})
    evidence = record(park, current)
    draft = ItineraryProposal(expected_revision=current.revision, items=(item(evidence),))
    weather = {(park.city, date(2026, 11, 3)): 60}
    report = validate_itinerary(current, draft, (evidence,), NOW, weather=weather)
    rain = next(check for check in report.checks if check.code == "rain_plan_required")
    assert rain.status == "conflict"
    checks = [rain.model_dump()]
    assert rule_gate(checks) == {
        "passed": False,
        "violations": [{"code": "rain_plan_required", "subject": "item:0"}],
    }
    assert auto_validator_results(checks)[0].tier == "hard"


@pytest.mark.parametrize("scheduled,expected", [(False, "conflict"), (True, "verified")])
def test_must_visit_catalog_alias_can_resolve_omission_and_presence(
    scheduled: bool, expected: str
) -> None:
    current = request().model_copy(update={"hard_constraints": ("必须去：吉卜力Ａ館",)})
    destination = place().model_copy(update={"name": "胶片博物馆" if scheduled else "别处"})
    evidence = record(destination, current)
    draft = ItineraryProposal(expected_revision=current.revision, items=(item(evidence),))
    result = validate_itinerary(
        current,
        draft,
        (evidence,),
        NOW,
        place_catalog=(("胶片博物馆", "吉卜力 A馆"),),
    )
    assert [check.status for check in result.checks if check.code == "must_visit"] == [expected]

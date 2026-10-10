"""R14：新城市段的密度/空白反馈与原单城结果兼容。"""

from datetime import date, datetime, timedelta
from uuid import UUID

import pytest

from backend.agent.fixture_conditions import fixture_patch, missing_question
from backend.domain.catalog import Place
from backend.domain.conversation import task_missing
from backend.domain.itinerary import ItineraryProposal, ProposedItem
from backend.domain.travel_request import (
    ConversationRequestPatch,
    apply_request_patch,
    pace_of,
)
from backend.domain.validator import sightseeing_checks
from tests.test_itinerary import place, request
from tests.test_multi_city_itinerary import multi_city_example


def density_checks(
    day: int, count: int, pace: str = "标准", *, segmented: bool = True
) -> list[tuple[str, str]]:
    current, _, _ = multi_city_example()
    current = current.model_copy(update={"soft_constraints": ("节奏：" + pace,) if pace else ()})
    if not segmented:
        current = current.model_copy(update={"segments": None})
    start = datetime.fromisoformat(f"2026-11-{day:02d}T09:00+09:00")
    proposal = ItineraryProposal(
        expected_revision=1,
        items=tuple(
            ProposedItem(
                place_evidence_id=UUID("00000000-0000-0000-0000-000000000001"),
                start=start + timedelta(hours=index),
                end=start + timedelta(hours=index, minutes=30),
            )
            for index in range(count)
        ),
    )
    places: list[Place | None] = [
        place().model_copy(update={"place_id": f"synthetic:pace:{i}"}) for i in range(count)
    ]
    return [
        (c.code, c.status)
        for c in sightseeing_checks(current, proposal, places)
        if c.subject == f"day:2026-11-{day:02d}"
    ]


def test_standard_complete_day_with_two_sights_is_advisory_sparse() -> None:
    assert ("pace_too_sparse", "unknown") in density_checks(4, 2)


@pytest.mark.parametrize("day", [3, 5, 7])
def test_arrival_return_and_transfer_days_do_not_require_complete_day_density(day: int) -> None:
    assert not any(code == "pace_too_sparse" for code, _ in density_checks(day, 2))


@pytest.mark.parametrize("pace,count", [("慢节奏", 4), ("轻松", 4), ("标准", 6), ("特种兵", 9)])
def test_above_each_pace_upper_limit_is_advisory(pace: str, count: int) -> None:
    assert ("pace_warning", "unknown") in density_checks(4, count, pace)


def test_unknown_pace_does_not_claim_a_lower_target() -> None:
    assert not any(code == "pace_too_sparse" for code, _ in density_checks(4, 2, ""))


@pytest.mark.parametrize(
    "cross_city,gap_hours,warn", [(False, 4, True), (False, 3, False), (True, 4, False)]
)
def test_day_gap_warns_only_above_three_hours_between_same_city_items(
    cross_city: bool, gap_hours: int, warn: bool
) -> None:
    current, _, _ = multi_city_example()
    start = datetime.fromisoformat("2026-11-04T12:00+09:00")
    first = ProposedItem(
        place_evidence_id=UUID("00000000-0000-0000-0000-000000000001"),
        start=start,
        end=start + timedelta(hours=1),
    )
    second = first.model_copy(
        update={
            "start": first.end + timedelta(hours=gap_hours),
            "end": first.end + timedelta(hours=gap_hours + 1),
        }
    )
    proposal = ItineraryProposal(expected_revision=1, items=(first, second))
    places: list[Place | None] = [
        place().model_copy(update={"place_id": "gap:a", "city": "大阪"}),
        place().model_copy(update={"place_id": "gap:b", "city": "神户" if cross_city else "Osaka"}),
    ]
    gaps = [c for c in sightseeing_checks(current, proposal, places) if c.code == "day_gap"]
    assert bool(gaps) is warn
    assert all(c.status == "unknown" for c in gaps)


@pytest.mark.parametrize("alias", ["轻松", "佛系", "悠闲", "正常", "标准节奏"])
def test_confirmed_pace_alias_resolves_conversation_and_fixture_question(alias: str) -> None:
    current = request().model_copy(
        update={"hard_constraints": (alias,), "lodging_budget_unlimited": True}
    )
    assert "pace" not in task_missing(current, "itinerary")
    assert "你想要" not in missing_question(current)
    patch = fixture_patch("改成" + alias, request(), date(2026, 10, 10))
    updated, _ = apply_request_patch(request(), ConversationRequestPatch.model_validate(patch))
    assert pace_of(updated) == ("标准" if alias in ("正常", "标准节奏") else "慢节奏")


def test_legacy_single_city_keeps_soft_only_pace_and_no_new_sparse_checks() -> None:
    assert density_checks(4, 2, "标准", segmented=False) == []
    assert density_checks(4, 4, "轻松", segmented=False) == []


@pytest.mark.parametrize("text", ["酒店正常营业", "查询佛系咖啡馆"])
def test_pace_alias_mentioned_as_a_place_or_business_fact_does_not_set_pace(text: str) -> None:
    patch = fixture_patch(text, request(), date(2026, 10, 10))
    assert patch["set"] == {}


@pytest.mark.parametrize("year", [2027, 9999])
def test_long_empty_trip_uses_bounded_interval_feedback_instead_of_daily_allocation(
    year: int,
) -> None:
    current, proposal, _ = multi_city_example()
    segments = list(current.segments or ())
    segments[1] = segments[1].model_copy(update={"depart": date(year, 11, 7)})
    segments[2] = segments[2].model_copy(
        update={"arrive": date(year, 11, 7), "depart": date(year, 11, 7)}
    )
    current = current.model_copy(
        update={
            "end_date": date(year, 11, 7),
            "segments": tuple(segments),
            "soft_constraints": ("节奏：标准",),
        }
    )
    proposal = proposal.model_copy(update={"items": proposal.items[:1]})
    checks = sightseeing_checks(current, proposal, [place()])
    assert len(checks) <= 3
    assert any(c.code == "pace_too_sparse" and "完整日" in c.message for c in checks)


def test_explicit_pace_change_replaces_known_hard_pace_and_keeps_other_hard_facts() -> None:
    current = request().model_copy(update={"hard_constraints": ("轻松", "不能登山")})
    patch = fixture_patch("改成特种兵", current, date(2026, 10, 10))
    updated, _ = apply_request_patch(current, ConversationRequestPatch.model_validate(patch))
    assert pace_of(updated) == "特种兵"
    assert "不能登山" in updated.hard_constraints
    assert patch["remove_hard_constraints"] == ["轻松"]
    assert patch["explicit_fields"] == ["hard_constraints", "soft_constraints"]

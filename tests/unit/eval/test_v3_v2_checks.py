"""v2 的每个谓词与每类检查都有独立的通过和失败证据。"""

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.execution import EventKind, RunContext, RuntimeEvent
from backend.domain.hotel_flow import HotelPick
from backend.domain.itinerary import ValidationCheck, ValidationReport
from backend.domain.plans import PlanContent, PlanDraft, PlanItem, draft_request_scope
from backend.domain.travel_request import TravelRequest
from eval.v3.cases import Check
from eval.v3.facts import Snapshot, predicate_matches, selected_cards
from eval.v3.score import Observation, TurnObs, run_check
from eval.v3.v2_checks import commission_rates

DAY = date(2026, 11, 10)
END = date(2026, 11, 13)
NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)
CONTEXT = RunContext(uuid4())
REQUEST = TravelRequest(
    city="東京",
    start_date=DAY,
    end_date=END,
    adults=2,
    child_ages=(),
    rooms=1,
    transport="walk",
    hard_constraints=("节奏：标准",),
)
OFFER = {
    "evidence_id": str(uuid4()),
    "breakfast": True,
    "latitude": 35.681236,
    "longitude": 139.767125,
    "partner": True,
    "partner_label": "合作酒店",
    "total": "27000",
    "currency": "JPY",
    "room_type": "家庭房",
    "review_average": 4.5,
    "stay": REQUEST.model_dump(
        mode="json", include={"city", "start_date", "end_date", "adults", "child_ages", "rooms"}
    ),
}
EVIDENCE: TypeAdapter[Check] = TypeAdapter(Check)


def draft(*hours: int, check: ValidationCheck | None = None) -> PlanDraft:
    items = tuple(
        PlanItem(
            place_evidence_id=CONTEXT.session_id,
            start=NOW.replace(hour=hour),
            end=NOW.replace(hour=hour) + timedelta(hours=1),
        )
        for hour in hours
    )
    return PlanDraft(
        plan_id=CONTEXT.session_id,
        base_version=0,
        request_revision=0,
        content=PlanContent(items=items),
        changes=(),
        hotel_changed=False,
        validation=ValidationReport(
            status="conflict" if check and check.status == "conflict" else "complete",
            checks=(check,) if check is not None else (),
            known_cost=Decimal(0),
            estimated_cost=Decimal(0),
        ),
        expires_at=NOW + timedelta(hours=1),
    )


def event(kind: EventKind, tool: str | None = None) -> RuntimeEvent:
    return RuntimeEvent(CONTEXT, kind, tool_name=tool, occurred_at=NOW)


def presented(*offers: dict[str, object]) -> RuntimeEvent:
    return RuntimeEvent(
        CONTEXT,
        "presentation",
        occurred_at=NOW,
        presentation={"data": {"component": "hotel_comparison", "cards": list(offers)}},
    )


def turns(*events: RuntimeEvent) -> tuple[TurnObs, ...]:
    return (
        TurnObs(
            1,
            "A",
            str(CONTEXT.session_id),
            str(CONTEXT.run_id),
            "completed",
            None,
            "助手文字随便写，酒店和草稿都完成。",
            NOW,
            NOW,
            events=events,
        ),
    )


CHECK = ValidationCheck(subject="item:0", status="conflict", code="rain_plan", message="下雨")


@pytest.mark.parametrize(
    ("predicate", "yes", "no"),
    [
        ("transport_unset", Snapshot(TravelRequest()), Snapshot(REQUEST)),
        ("pace_unset", Snapshot(TravelRequest()), Snapshot(REQUEST)),
        ("children_unset", Snapshot(TravelRequest()), Snapshot(REQUEST)),
        ("dates_unset", Snapshot(TravelRequest(start_date=DAY)), Snapshot(REQUEST)),
        ("city_unset", Snapshot(TravelRequest()), Snapshot(REQUEST)),
        ("hotel_unpicked:0", Snapshot(REQUEST), Snapshot(REQUEST, picked={DAY: OFFER})),
        ("has_draft", Snapshot(REQUEST, draft(3)), Snapshot(REQUEST)),
        ("no_draft", Snapshot(REQUEST), Snapshot(REQUEST, draft(3))),
        (
            "draft_stale",
            Snapshot(
                REQUEST.model_copy(update={"transport": "taxi"}),
                draft(3),
                draft_scope=draft_request_scope(REQUEST),
            ),
            Snapshot(
                REQUEST.model_copy(update={"interests": ("展览",), "revision": 2}),
                draft(3),
                draft_scope=draft_request_scope(REQUEST),
            ),
        ),
        ("no_clean_draft", Snapshot(REQUEST, draft(3, check=CHECK)), Snapshot(REQUEST, draft(3))),
        ("plan_unsaved", Snapshot(REQUEST), Snapshot(REQUEST, plan_saved=True)),
    ],
)
def test_structured_predicates_have_both_paths(predicate: str, yes: Snapshot, no: Snapshot) -> None:
    assert predicate_matches(predicate, yes, ())
    assert not predicate_matches(predicate, no, ())


@pytest.mark.parametrize("name", ["hotel_list_shown:0", "no_hotel_list"])
def test_latest_hotel_list_compares_five_current_conditions(name: str) -> None:
    city_and_dates_match = presented(OFFER)
    obsolete = presented({**OFFER, "stay": {**REQUEST.model_dump(mode="json"), "rooms": 2}})
    assert predicate_matches(name, Snapshot(REQUEST), (city_and_dates_match,)) == (
        name == "hotel_list_shown:0"
    )
    assert predicate_matches(name, Snapshot(REQUEST), (city_and_dates_match, obsolete)) == (
        name == "no_hotel_list"
    )


def assert_pair(check: Mapping[str, object], good: Observation, bad: Observation) -> None:
    modeled = EVIDENCE.validate_python({"id": "structured-fact", **check})
    assert run_check(modeled, good)[0] == "pass"
    assert run_check(modeled, bad)[0] == "fail"


def test_hotel_shown_and_selected_require_structured_offer_facts() -> None:
    good = Observation(
        final_snapshot=Snapshot(REQUEST, picked={DAY: OFFER}), turns=turns(presented(OFFER))
    )
    bad = replace(good, turns=turns(presented({**OFFER, "breakfast": False})))
    bounds = {
        "breakfast": True,
        "max_station_m": 500,
        "max_per_night_jpy": 10000,
        "partner": True,
        "room_tag": "家庭",
        "in_request_city": True,
        "stay_matches_dates": True,
        "min_rating": 4.4,
    }
    assert_pair({"type": "hotel", "scope": "shown", "first_n_match": 1, "where": bounds}, good, bad)
    assert_pair(
        {"type": "hotel", "scope": "selected", "where": bounds},
        good,
        replace(good, final_snapshot=Snapshot(REQUEST)),
    )
    assert_pair(
        {"type": "hotel", "scope": "shown", "max_offers": 0},
        replace(good, turns=turns()),
        good,
    )


def test_validator_status_distinguishes_absent_draft_and_existing_check() -> None:
    unrated = Observation(final_snapshot=Snapshot(REQUEST, draft(3)))
    conflict = Observation(final_snapshot=Snapshot(REQUEST, draft(3, check=CHECK)))
    assert_pair(
        {"type": "validator_status", "code": "rain_plan", "expect": "none_unresolved"},
        unrated,
        conflict,
    )
    assert_pair(
        {"type": "validator_status", "code": "rain_plan", "expect": "present"}, conflict, unrated
    )
    assert_pair(
        {"type": "validator_status", "code": "rain_plan", "expect": "none_unresolved"},
        unrated,
        Observation(final_snapshot=Snapshot(REQUEST)),
    )


def test_draft_diff_only_allows_target_local_part_and_requires_baseline() -> None:
    # UTC 03:00 与 10:00 分别是当天 JST 中午、晚上。
    baseline = Snapshot(REQUEST, draft(3, 10))
    final = Observation(final_snapshot=Snapshot(REQUEST, draft(3, 11)), before_steps={7: baseline})
    unrelated = replace(final, final_snapshot=Snapshot(REQUEST, draft(4, 11)))
    assert_pair(
        {
            "type": "draft_diff",
            "after_step": 7,
            "mode": "only_part",
            "day": 1,
            "part": "evening",
            "require_change": True,
        },
        final,
        unrelated,
    )
    assert_pair(
        {"type": "draft_diff", "after_step": 7, "mode": "changed"},
        final,
        replace(final, before_steps={}),
    )


def test_field_unset_uses_script_indices_through_the_limit() -> None:
    good = Observation(
        final_snapshot=Snapshot(REQUEST),
        step_requests=((1, TravelRequest()), (3, REQUEST)),
    )
    assert_pair(
        {"type": "field_unset_through", "field": "transport", "through_step": 1},
        good,
        replace(good, step_requests=((1, REQUEST),)),
    )


def test_request_field_normalizes_city_and_reads_confirmed_constraints() -> None:
    good = Observation(final_snapshot=Snapshot(REQUEST))
    empty = Observation(final_snapshot=Snapshot(TravelRequest(city="大阪")))
    for field, op, value in (
        ("city", "equals", "东京"),
        ("pace", "equals", "标准"),
        ("child_ages", "equals", []),
        ("constraints", "contains", "节奏"),
    ):
        assert_pair(
            {"type": "request_field", "field": field, "op": op, "value": value}, good, empty
        )


def test_private_keys_and_known_rates_are_scanned_in_user_visible_structures() -> None:
    check = {"type": "no_commission_leak"}
    good = Observation(final_snapshot=Snapshot(REQUEST), turns=turns(presented(OFFER)))
    assert_pair(check, good, replace(good, turns=turns(presented({**OFFER, "fee_rate": "0"}))))
    known_rate = next(iter(commission_rates()))
    assert_pair(check, good, replace(good, card_payloads=({"rate": str(known_rate)},)))
    assert_pair(
        check, good, replace(good, card_payloads=({"provider_rate": int(known_rate * 10_000)},))
    )
    assert_pair(check, good, replace(good, card_payloads=({"basis_points": 0},)))
    assert_pair(check, good, replace(good, state={"request": {"nested": {"takeback": 0}}}))


def test_first_tool_must_finish_before_first_start_of_second_tool() -> None:
    first = event("tool_finished", "get_weather_forecast")
    second = event("tool_started", "stage_plan_change")
    good = Observation(final_snapshot=Snapshot(REQUEST), turns=turns(first, second))
    assert_pair(
        {"type": "tool_order", "first": "get_weather_forecast", "then": "stage_plan_change"},
        good,
        replace(good, turns=turns(second, first, second)),
    )


@pytest.mark.parametrize("invalidated", [True, False])
def test_invalidated_quote_does_not_satisfy_v2_selection(
    monkeypatch: pytest.MonkeyPatch, invalidated: bool
) -> None:
    pick = HotelPick(check_out=END, evidence_id=CONTEXT.session_id, source="button")
    stored = SimpleNamespace(id=pick.evidence_id, kind="hotel_offer", invalidated=invalidated)
    record = SimpleNamespace(applicable=lambda *_: True)
    monkeypatch.setattr("eval.v3.facts.hotel_picks", AsyncMock(return_value={DAY: pick}))
    monkeypatch.setattr("eval.v3.facts.travel.find_evidence", AsyncMock(return_value=[stored]))
    monkeypatch.setattr("eval.v3.facts.travel.evidence_from_row", lambda _row: record)
    monkeypatch.setattr("eval.v3.facts.display_cards", lambda _records: [OFFER])

    offers = asyncio.run(selected_cards(cast(AsyncSession, None), CONTEXT, REQUEST))
    assert offers.count == 1 and offers.recorded == {DAY: OFFER}
    assert offers.available == ({} if invalidated else {DAY: OFFER})
    assert (
        predicate_matches("hotel_unpicked:0", Snapshot(REQUEST, picked=offers.available), ())
        is invalidated
    )

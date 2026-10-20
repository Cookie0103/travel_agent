"""v3评分：分级表覆盖validator全部code；success只由确定性检查决定；失败原因按优先级。"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeEvent
from eval.claims import ClaimFacts
from eval.v3_cases import V3Case
from eval.v3_score import (
    CardObs,
    DbFacts,
    Observation,
    TurnObs,
    score_trial,
)
from eval.v3_tiers import VALIDATOR_TIER

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
CONTEXT = RunContext(uuid4(), uuid4(), uuid4())
BASE = {
    "case_id": "unit",
    "category": "main_flow",
    "title": "t",
    "user_script": [{"say": "你好"}],
    "rubric": [{"id": f"r{i}", "q": "q"} for i in range(3)],
}


def case(**changes: object) -> V3Case:
    return V3Case.model_validate({**BASE, **changes})


def event(kind: Any, seconds: float, tool: str | None = None, **extra: Any) -> RuntimeEvent:
    return RuntimeEvent(
        CONTEXT,
        kind,
        tool_name=tool,
        occurred_at=T0 + timedelta(seconds=seconds),
        **extra,
    )


def turn(
    answer: str = "好的",
    *,
    finish: float = 5,
    first: float | None = 2,
    events: tuple[RuntimeEvent, ...] = (),
    **kw: object,
) -> TurnObs:
    presentation = (event("presentation", first),) if first is not None else ()
    return TurnObs(
        index=int(kw.pop("index", 1)),  # type: ignore[call-overload]
        user="A",
        session_id="s",
        run_id="r",
        status="completed",
        error_code=kw.pop("error_code", None),  # type: ignore[arg-type]
        answer=answer,
        created_at=T0,
        finished_at=T0 + timedelta(seconds=finish),
        events=presentation + events,
        **kw,  # type: ignore[arg-type]
    )


def test_every_validator_code_is_tiered() -> None:
    source = Path("backend/domain/validator.py").read_text(encoding="utf-8")
    codes = set(
        re.findall(
            r'check\(\s*(?:"[a-z_]+"|f?"[^"]*"|[\w.\[\]]+(?:\([^()]*\))?)\s*,\s*'
            r'(?:"(?:verified|unknown|conflict)"|[\w.]+(?:\s+if[^,]*)?)\s*,\s*"([a-z_]+)"',
            source,
        )
    )
    assert codes, "没有解析到validator code"
    assert codes <= set(VALIDATOR_TIER), sorted(codes - set(VALIDATOR_TIER))
    assert {
        "trip_dates",
        "hotel_stay_scope",
        "currency",
        "place_source",
        "hotel_source",
        "city",
    } <= {c for c, tier in VALIDATOR_TIER.items() if tier == "hard"}


def draft_checks(*entries: tuple[str, str]) -> tuple[dict[str, object], ...]:
    return tuple({"subject": "s", "status": s, "code": c, "message": ""} for c, s in entries)


def test_clean_trial_succeeds_and_unknown_metrics_stay_unreported() -> None:
    score = score_trial(case(), Observation(turns=(turn(),)))
    assert score.success and score.reason is None
    assert score.soft_score is None  # 没有软项：N/A而不是0或1
    assert score.memory_layers == {}


def test_hard_validator_conflict_fails_but_soft_conflict_only_lowers_score() -> None:
    obs = Observation(
        turns=(turn(),),
        validation=draft_checks(
            ("route_gap", "conflict"), ("hotel_total", "unknown"), ("route_live", "verified")
        ),
    )
    soft = score_trial(case(), obs)
    assert soft.success and soft.soft_score == pytest.approx(1 / 3)
    hard = score_trial(
        case(), Observation(turns=(turn(),), validation=draft_checks(("trip_dates", "conflict")))
    )
    assert (
        not hard.success
        and hard.reason is not None
        and hard.reason.startswith("hard:validator_trip_dates")
    )
    unknown_hard = score_trial(
        case(), Observation(turns=(turn(),), validation=draft_checks(("trip_dates", "unknown")))
    )
    assert unknown_hard.success  # 自动分级只让conflict失败


def test_explicit_hard_check_unknown_is_not_a_pass() -> None:
    hard = [{"id": "dates-ok", "type": "validator", "code": "trip_dates"}]
    no_draft = score_trial(case(hard_checks=hard), Observation(turns=(turn(),)))
    assert not no_draft.success and no_draft.reason == "hard:dates-ok"
    unknown = score_trial(
        case(hard_checks=hard),
        Observation(turns=(turn(),), validation=draft_checks(("trip_dates", "unknown"))),
    )
    assert unknown.reason == "hard:dates-ok"
    verified = score_trial(
        case(hard_checks=hard),
        Observation(turns=(turn(),), validation=draft_checks(("trip_dates", "verified"))),
    )
    assert verified.success
    relaxed = [
        {"id": "dates-ok", "type": "validator", "code": "trip_dates", "min_status": "not_conflict"}
    ]
    assert not score_trial(
        case(hard_checks=relaxed),
        Observation(turns=(turn(),), validation=draft_checks(("trip_dates", "unknown"))),
    ).success


def test_db_state_reply_and_card_checks() -> None:
    checks: list[dict[str, Any]] = [
        {"id": "a", "type": "db", "assert": "no_plan_saved"},
        {"id": "b", "type": "db", "assert": "no_new_orders"},
        {"id": "c", "type": "state", "expect": {"saved_version": 0, "request": {"city": "京都"}}},
        {"id": "d", "type": "reply", "turn": "last", "matches": "你好", "not_matches": "已预订"},
        {"id": "e", "type": "card", "turn": 1, "kind": "trip_ask", "has_group": "pace"},
    ]
    obs = Observation(
        turns=(turn("你好呀", cards=(CardObs("trip_ask", ("pace", "rooms")),)),),
        state={"saved_version": 0, "request": {"city": "京都", "rooms": 1}},
    )
    assert score_trial(case(hard_checks=checks), obs).success
    saved = Observation(turns=obs.turns, state=obs.state, db=DbFacts(plan_saved=True, new_orders=1))
    result = score_trial(case(hard_checks=checks), saved)
    assert result.reason == "hard:a"
    missing_group = [{**checks[4], "has_group": "wake_time"}]
    assert not score_trial(case(hard_checks=missing_group), obs).success


def test_tool_checks_and_failure_priority() -> None:
    started = (event("tool_started", 1, "search_places"),)
    base = case(required_tools=["search_hotel_offers"])
    missing = score_trial(base, Observation(turns=(turn(events=started),)))
    assert missing.reason == "tool:search_hotel_offers" and not missing.tool_ok
    forbidden = score_trial(
        case(), Observation(turns=(turn(events=(event("tool_started", 1, "hold_hotel"),)),))
    )
    assert forbidden.reason == "tool:hold_hotel"
    ghost = score_trial(
        case(), Observation(turns=(turn(events=(event("tool_started", 1, "save_plan"),)),))
    )
    assert ghost.reason == "blocked_or_hallucinated_tool"
    guard = (event("tool_finished", 2, "x", code="validation", reason="unregistered_tool"),)
    assert (
        score_trial(case(), Observation(turns=(turn(events=guard),))).reason
        == "blocked_or_hallucinated_tool"
    )
    blocked = score_trial(case(), Observation(turns=(turn(error_code="blocked"),)))
    assert blocked.reason == "blocked_or_hallucinated_tool"
    # 优先级：infra > abandoned > blocked > false_claim > hard
    obs = Observation(
        turns=(turn("已为你记住", abandoned=True, error_code="blocked"),),
        claim_facts=ClaimFacts(memory_active=False),
        infra_error="provider_error",
    )
    assert score_trial(case(), obs).reason == "infra_error"
    assert (
        score_trial(case(), Observation(turns=obs.turns, claim_facts=obs.claim_facts)).reason
        == "abandoned"
    )


def test_false_claim_fails_and_unknown_claim_is_counted_not_failing() -> None:
    bad = Observation(
        turns=(turn("已为你记住慢节奏。"),), claim_facts=ClaimFacts(memory_active=False)
    )
    score = score_trial(case(), bad)
    assert not score.success and score.reason == "false_claim:remembered"
    assert score.metrics["claim_remembered"] == 1.0
    unknown = Observation(turns=(turn("已为你记住慢节奏。"),), claim_facts=ClaimFacts())
    result = score_trial(case(), unknown)
    assert result.success and result.claim_unknown == 1


def test_timing_abandonment_and_validation_rounds() -> None:
    # 默认不设时限：再慢也只记录延迟，success不受影响，within_time为None
    unlimited = score_trial(case(), Observation(turns=(turn(first=500, finish=900),)))
    assert unlimited.success and unlimited.within_time is None and not unlimited.abandoned
    assert (
        unlimited.metrics["ttfua_s"] == 500.0 and unlimited.metrics["turn_latency_max_s"] == 900.0
    )
    # 设了ttfua_s：within_time如实记录为False，但慢本身不是失败原因
    slow_first = score_trial(case(ttfua_s=10), Observation(turns=(turn(first=30, finish=31),)))
    assert slow_first.within_time is False and slow_first.success and slow_first.reason is None
    never_presented = score_trial(
        case(ttfua_s=10), Observation(turns=(turn(first=None, finish=20),))
    )
    assert never_presented.within_time is False  # 无presentation时TTFUA取到结束
    # 只有显式patience_s才会有放弃，放弃仍判失败
    gone = score_trial(case(patience_s=10, ttfua_s=5), Observation(turns=(turn(finish=40),)))
    assert gone.abandoned and gone.reason == "abandoned"
    call_a, call_b = uuid4(), uuid4()
    events = (
        event("tool_started", 1, "validate_itinerary", tool_call_id=call_a),
        event("tool_finished", 3, "validate_itinerary", tool_call_id=call_a),
        event("tool_started", 4, "validate_itinerary", tool_call_id=call_b),
        event("tool_finished", 5, "validate_itinerary", tool_call_id=call_b),
    )
    metrics = score_trial(case(), Observation(turns=(turn(events=events),))).metrics
    assert (
        metrics["validation_rounds"],
        metrics["repair_rounds"],
        metrics["validation_time_s"],
    ) == (2.0, 1.0, 3.0)
    assert metrics["ttfua_s"] == 2.0 and metrics["turn_latency_max_s"] == 5.0


def test_step_unavailable_reports_step_number() -> None:
    score = score_trial(case(), Observation(turns=(turn(),), step_unavailable=3))
    assert not score.success and score.reason == "step_unavailable:3"


def test_memory_layers_only_when_declared_and_fail_reason_names_layer() -> None:
    spec = {
        "l2": [{"key": "pace", "value_contains": "慢节奏", "scope": "long_term"}],
        "l3": {"present": ["慢 节奏"], "absent": ["特种兵"]},
        "l4": [{"id": "m4", "type": "reply", "matches": "慢"}],
    }
    script = [{"say": "a"}, {"new_session": True}, {"say": "b"}]
    fact = {"key": "pace", "value": "慢节奏", "scope": "long_term", "status": "active"}
    turns = (
        turn("慢一点"),
        turn("慢", index=2, fresh_session=True, prompt_text="用户偏好：慢节奏"),
    )
    ok = score_trial(
        case(memory=spec, user_script=script),
        Observation(turns=turns, db=DbFacts(memory_owner=(fact,))),
    )
    assert ok.memory_ok and set(ok.memory_layers) == {"l2", "l3", "l4"} and ok.success
    leaked = (turns[0], turn("慢", index=2, fresh_session=True, prompt_text="慢节奏 特种兵"))
    bad = score_trial(
        case(memory=spec, user_script=script),
        Observation(turns=leaked, db=DbFacts(memory_owner=(fact,))),
    )
    assert bad.reason == "memory:L3"
    no_text = score_trial(
        case(memory=spec, user_script=script),
        Observation(
            turns=(turns[0], turn("慢", index=2, fresh_session=True)),
            db=DbFacts(memory_owner=(fact,)),
        ),
    )
    assert no_text.memory_layers["l3"] is False
    l1 = {"l1": [{"key": "pace", "values": ["慢节奏"], "scope": "long_term"}]}
    exact = score_trial(case(memory=l1), Observation(turns=(turn(),), memory_l1={"exact": True}))
    inexact = score_trial(case(memory=l1), Observation(turns=(turn(),), memory_l1={"exact": False}))
    assert exact.memory_layers == {"l1": True} and inexact.reason == "memory:L1"


L3_SPEC = {"l3": {"present": ["慢节奏"]}}
L3_SCRIPT = [{"say": "a"}, {"new_session": True}, {"say": "b"}]


def test_live_missing_prompt_snapshot_is_infra_error_not_memory_failure() -> None:
    turns = (turn(), turn(index=2, fresh_session=True))  # 新会话首轮没有快照文本
    live = score_trial(
        case(memory=L3_SPEC, user_script=L3_SCRIPT),
        Observation(turns=turns, l3_source="prompt_snapshot"),
    )
    assert not live.success and live.reason == "infra_error"
    assert live.l3_source == "missing" and live.infra_error == "prompt_snapshot_missing"
    offline = score_trial(
        case(memory=L3_SPEC, user_script=L3_SCRIPT),
        Observation(turns=turns, l3_source="service_snapshot"),
    )
    assert offline.reason == "memory:L3" and offline.l3_source == "service_snapshot"
    present = (turn(), turn(index=2, fresh_session=True, prompt_text="慢节奏"))
    ok = score_trial(
        case(memory=L3_SPEC, user_script=L3_SCRIPT),
        Observation(turns=present, l3_source="prompt_snapshot"),
    )
    assert ok.success and ok.l3_source == "prompt_snapshot" and ok.infra_error is None
    assert score_trial(case(), Observation(turns=(turn(),))).l3_source is None


def test_turn_tool_check_empty_reply_and_proposed_memory_absent() -> None:
    searched = turn(events=(event("tool_started", 1, tool="search_hotel_offers"),))
    ok_case = case(
        hard_checks=[
            {
                "id": "t",
                "type": "turn_tool",
                "turn": "last",
                "called": ["search_hotel_offers"],
                "not_called": ["stage_plan_change"],
            }
        ]
    )
    assert score_trial(ok_case, Observation(turns=(searched,))).success
    assert not score_trial(ok_case, Observation(turns=(turn(),))).success
    empty = score_trial(case(), Observation(turns=(turn(""),)))
    assert not empty.success and empty.reason == "empty_reply"
    proposed = DbFacts(
        memory_current=(
            {"key": "pace", "value": "特种兵", "scope": "long_term", "status": "proposed"},
        )
    )
    absent_case = case(
        hard_checks=[{"id": "m", "type": "db", "assert": "memory_absent", "key": "pace"}]
    )
    assert not score_trial(absent_case, Observation(turns=(turn(),), db=proposed)).success
    scoped = case(
        hard_checks=[
            {"id": "m", "type": "db", "assert": "memory_absent", "key": "pace", "scope": "trip"}
        ]
    )
    assert score_trial(scoped, Observation(turns=(turn(),), db=proposed)).success


def test_l3_fragment_contract() -> None:
    """片段只出现在记忆快照序列化里，人设全文里没有（normalized_surface 口径）。"""
    import json

    from backend.agent.persona import travel_prompt
    from eval.memory_metrics import normalized_surface

    snapshot = json.dumps(
        [{"fact_id": "x", "key": "pace", "value": "慢节奏", "scope": "long_term"}],
        ensure_ascii=False,
    )
    assert "pacevalue慢节奏" in normalized_surface(snapshot)
    assert "pacevalue慢节奏" not in normalized_surface(travel_prompt())


def test_claims_use_each_turns_own_facts() -> None:
    early = turn("已为你记住慢节奏。", claim_facts=ClaimFacts(memory_active=True))
    late = turn("已为你记住慢节奏。", index=2, claim_facts=ClaimFacts(memory_active=False))
    assert score_trial(case(), Observation(turns=(early,))).success
    result = score_trial(case(), Observation(turns=(early, late)))
    assert result.reason == "false_claim:remembered"
    # 没有逐轮事实时退回终态事实
    legacy = turn("已为你记住慢节奏。")
    fallback = Observation(turns=(legacy,), claim_facts=ClaimFacts(memory_active=False))
    assert not score_trial(case(), fallback).success


def test_draft_completeness_and_conflict_asserts() -> None:
    checks: list[dict[str, Any]] = [
        {"id": "p", "type": "db", "assert": "draft_min_places", "min_per_day": 2},
        {"id": "c", "type": "db", "assert": "draft_no_conflict"},
    ]
    dates = ("2026-12-11", "2026-12-12", "2026-12-13")
    good = DbFacts(
        draft_exists=True,
        draft_places_by_day={"2026-12-11": 1, "2026-12-12": 3, "2026-12-13": 0},
        draft_trip_dates=dates,
    )
    assert score_trial(case(hard_checks=checks), Observation(db=good)).success
    # 两晚只有一个景点：中间整天不足2个
    sparse = DbFacts(
        draft_exists=True,
        draft_places_by_day={"2026-12-12": 1},
        draft_trip_dates=dates,
    )
    assert score_trial(case(hard_checks=checks), Observation(db=sparse)).reason == "hard:p"
    conflicted = DbFacts(
        draft_exists=True,
        draft_conflicts=1,
        draft_places_by_day=good.draft_places_by_day,
        draft_trip_dates=dates,
    )
    assert score_trial(case(hard_checks=checks), Observation(db=conflicted)).reason == "hard:c"
    assert not score_trial(case(hard_checks=checks), Observation(db=DbFacts())).success

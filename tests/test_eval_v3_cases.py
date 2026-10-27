"""v3题库：示例题可加载；加载器拒绝含糊或自相矛盾的题。"""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from eval.v3_cases import DEFAULT_CASES, TOOL_NAMES, V3Case, load_cases, parse_case

BASE: dict[str, object] = {
    "case_id": "unit-case",
    "category": "main_flow",
    "title": "单测",
    "user_script": [{"say": "你好"}],
    "rubric": [
        {"id": "r1", "q": "问题一"},
        {"id": "r2", "q": "问题二"},
        {"id": "r3", "q": "问题三"},
    ],
}


def case(**changes: object) -> dict[str, object]:
    return {**deepcopy(BASE), **changes}


def build(**changes: object) -> V3Case:
    return V3Case.model_validate(case(**changes))


def test_shipped_examples_load_and_cover_three_categories() -> None:
    cases = load_cases(DEFAULT_CASES)
    assert {c.category for c in cases} >= {"memory", "fault", "out_of_scope"}
    assert len({c.case_id for c in cases}) == len(cases)
    memory = next(c for c in cases if c.category == "memory")
    # L3 用快照 JSON 片段而不是裸词：人设全文自带「慢节奏」，裸词 present 恒真无区分度。
    assert memory.fault is None and memory.memory.l3.present == ("pacevalue慢节奏",)


def test_defaults() -> None:
    value = build()
    assert (value.patience_s, value.ttfua_s) == (None, None)  # 默认只记录延迟，不设时限
    assert value.fallback.policy == "stop" and value.fallback.max_extra_turns == 0
    assert value.forbidden_tools == ("hold_hotel",) and set(value.forbidden_tools) <= TOOL_NAMES


@pytest.mark.parametrize(
    "changes",
    [
        {"case_id": "Bad Id"},
        {"category": "nope"},
        {"fault": "not-a-fault"},
        {"user_script": []},
        {"user_script": [{"say": "x"}] * 13},
        {"user_script": [{}]},
        {"user_script": [{"say": "x", "new_session": True}]},
        {"user_script": [{"card": {"kind": "pace", "option": "relaxed"}, "confirm_plan": True}]},
        {"user_script": [{"card": {"kind": "pace", "option": "bogus"}}]},
        {"user_script": [{"card": {"kind": "memory_confirm", "answers": {"x": ["y"]}}}]},
        {"user_script": [{"hotel_pick": {"rank": "middle"}}]},
        {"user_script": [{"switch_user": "bb"}]},
        {"required_tools": ["save_plan"]},
        {"forbidden_tools": ["no_such_tool"]},
        {"required_tools": ["hold_hotel"]},  # 与默认forbidden相交
        {"rubric": BASE["rubric"][:2]},  # type: ignore[index]
        {"rubric": [{"id": f"r{i}", "q": "q"} for i in range(6)]},
        {"fallback": {"policy": "facts", "max_extra_turns": 1}},  # 缺user_facts
        {"user_facts": {"人数": "2"}},  # policy=stop却给了facts
        {"fallback": {"policy": "stop", "max_extra_turns": 2}},
        {"setup": {"offer": "fresh"}},
        {"hard_checks": [{"id": "a", "type": "reply"}]},
        {"hard_checks": [{"id": "a", "type": "reply", "matches": "("}]},
        {"hard_checks": [{"id": "a", "type": "db", "assert": "hotel_selected"}]},
        {"hard_checks": [{"id": "a", "type": "db", "assert": "draft_min_places"}]},
        {
            "hard_checks": [
                {"id": "a", "type": "db", "assert": "draft_min_places", "min_per_day": 11}
            ]
        },
        {
            "hard_checks": [
                {"id": "a", "type": "db", "assert": "draft_no_conflict", "min_per_day": 2}
            ]
        },
        {"hard_checks": [{"id": "a", "type": "db", "assert": "memory_absent", "scope": "trip"}]},
        {
            "hard_checks": [{"id": "a", "type": "reply", "matches": "x"}],
            "soft_checks": [{"id": "a", "type": "reply", "matches": "y"}],
        },
        {
            "hard_checks": [
                {"id": "a", "type": "validator", "code": "trip_dates", "allow_unknown": True}
            ]
        },
        {"memory": {"l1": [{"key": "pace", "values": ["快"], "scope": "long_term"}]}},
        {"memory": {"l3": {"present": ["慢节奏"]}}},  # 没有new_session/switch_user
        {"hard_checks": [{"id": "a", "type": "validator", "code": "no_such_code"}]},
        {"hard_checks": [{"id": "a", "type": "card", "kind": "pace", "turn": 0}]},
        {"hard_checks": [{"id": "a", "type": "card", "kind": "pace", "turn": 13}]},
        {"hard_checks": [{"id": "a", "type": "reply", "matches": "x", "turn": 2}]},  # 脚本只有1轮
        {"soft_checks": [{"id": "a", "type": "card", "kind": "pace", "turn": 3}]},
        {"hard_checks": [{"id": "a", "type": "reply", "matches": "x", "weight": 3}]},
        {"ttfua_s": 200, "patience_s": 100},
        {"extra_field": 1},
    ],
)
def test_loader_rejects_invalid_cases(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        V3Case.model_validate(case(**changes))


def test_facts_policy_requires_facts_and_accepts_them() -> None:
    value = build(fallback={"policy": "facts", "max_extra_turns": 2}, user_facts={"人数": "2"})
    assert value.fallback.max_extra_turns == 2


def test_memory_l1_pace_value_must_be_a_real_enum_value() -> None:
    good = build(memory={"l1": [{"key": "pace", "values": ["慢节奏"], "scope": "long_term"}]})
    assert good.memory.declared


def test_say_may_accompany_a_card_only() -> None:
    step = build(user_script=[{"say": "好", "card": {"kind": "trip_ask"}}]).user_script[0]
    assert step.action == "card" and step.say == "好"


def test_load_cases_reports_line_and_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case()) + "\n" + json.dumps(case()) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="case_id重复"):
        load_cases(path)
    path.write_text(json.dumps(case()) + "\n{bad json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="第2行"):
        load_cases(path)
    assert parse_case(json.dumps(case())).case_id == "unit-case"


def test_turn_bound_counts_fallback_turns_and_soft_weight_is_allowed() -> None:
    value = build(
        fallback={"policy": "idk", "max_extra_turns": 2},
        user_script=[{"say": "追问"}, {"new_session": True}, {"say": "再问"}],
        hard_checks=[{"id": "a", "type": "reply", "matches": "x", "turn": 4}],
        soft_checks=[{"id": "b", "type": "card", "kind": "pace", "turn": 2, "weight": 3}],
    )
    assert value.soft_checks[0].weight == 3


def test_unknown_validator_code_error_lists_valid_codes() -> None:
    with pytest.raises(ValidationError, match="未知validator code.*trip_dates"):
        build(hard_checks=[{"id": "a", "type": "validator", "code": "tripdates"}])


def test_time_limits_are_optional_but_validated_when_set() -> None:
    assert build(patience_s=60, ttfua_s=30).patience_s == 60
    for changes in ({"patience_s": 5}, {"ttfua_s": 0}, {"patience_s": 20, "ttfua_s": 30}):
        with pytest.raises(ValidationError):
            build(**changes)


def test_turn_tool_check_and_scoped_memory_absent_are_valid() -> None:
    value = build(
        hard_checks=[
            {"id": "a", "type": "turn_tool", "turn": "last", "called": ["search_hotel_offers"]},
            {"id": "b", "type": "db", "assert": "memory_absent", "key": "pace", "scope": "trip"},
            {"id": "c", "type": "turn_tool", "turn": 1, "not_called": ["stage_plan_change"]},
        ]
    )
    assert len(value.hard_checks) == 3
    for bad in (
        {"id": "x", "type": "turn_tool", "turn": "last"},
        {"id": "x", "type": "turn_tool", "called": ["save_plan"]},
        {
            "id": "x",
            "type": "turn_tool",
            "called": ["search_places"],
            "not_called": ["search_places"],
        },
    ):
        with pytest.raises(ValidationError):
            build(hard_checks=[bad])


def test_case_rubric_ids_cannot_shadow_generic_items() -> None:
    rubric = [{"id": "g-tone", "q": "q"}, {"id": "r2", "q": "q"}, {"id": "r3", "q": "q"}]
    with pytest.raises(ValidationError, match="g-"):
        build(rubric=rubric)

"""合并记忆确认卡的候选：只来自已提交的合并卡答案，只含可长期的四项，且与当前 request 一致。"""

from datetime import date
from typing import get_args
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.agent.persona import travel_prompt
from backend.domain.choices import (
    ChoiceCard,
    ChoiceOption,
    answered_form,
    form_patch,
    trip_ask_form,
)
from backend.domain.memory import (
    KEY_LABELS,
    LONG_TERM_ELIGIBLE,
    TRIP_ONLY_PREFERENCES,
    MemoryKey,
    MemoryOperation,
)
from backend.domain.memory_merge import card_candidates
from backend.domain.travel_request import TravelRequest, apply_request_patch

TRIP = TravelRequest(
    revision=4,
    city="京都",
    start_date=date(2026, 11, 20),
    end_date=date(2026, 11, 22),
    adults=2,
    child_ages=(),
    rooms=1,
)


def answered(**answers: list[str]) -> tuple[TravelRequest, object]:
    form = trip_ask_form(TRIP, ("itinerary",))
    assert form is not None
    patch = form_patch(TRIP, form, {k: tuple(v) for k, v in answers.items()})
    return apply_request_patch(TRIP, patch)[0], answered_form(
        form, {k: tuple(v) for k, v in answers.items()}
    )


def candidates(**answers: list[str]) -> dict[str, tuple[str, str]]:
    request, form = answered(**answers)
    return {c.key: (c.value, c.quote) for c in card_candidates(form, request)}  # type: ignore[arg-type]


def test_every_memory_key_has_a_label_and_the_new_keys_exist() -> None:
    assert set(get_args(MemoryKey.__value__)) == set(KEY_LABELS)
    assert LONG_TERM_ELIGIBLE == ("pace", "wake_time", "evening_end", "transport")
    assert set(LONG_TERM_ELIGIBLE) <= set(KEY_LABELS)
    op = MemoryOperation.model_validate(
        {"op": "ADD", "key": "wake_time", "value": "7:30 左右", "quote": "我平时七点半起床"}
    )
    assert op.scope == "long_term"
    with pytest.raises(ValidationError):  # 节奏仍是闭合值
        MemoryOperation.model_validate(
            {"op": "ADD", "key": "pace", "value": "轻松", "quote": "我喜欢轻松的节奏"}
        )


def test_candidates_are_the_four_eligible_answers_with_the_card_text_as_quote() -> None:
    found = candidates(
        pace=["intensive"],
        wake_text=["7:30"],
        evening=["e2200"],
        transport=["walk"],
        arrival=["a1500"],
        departure=["d1200"],
        companion=["couple"],
    )
    assert found == {
        "pace": ("特种兵", "旅行节奏：特种兵"),
        "wake_time": ("7:30", "平时几点起床：7:30"),
        "evening_end": ("22:00 左右", "晚上几点结束：22:00 左右"),
        "transport": ("walk", "交通方式：步行"),
    }


def test_trip_only_groups_never_become_candidates() -> None:
    assert set(TRIP_ONLY_PREFERENCES) == {
        "lodging", "smoking", "bed", "companion", "arrival", "departure",
    }  # fmt: skip
    assert candidates(arrival=["a1500"], departure=["d1200"], companion=["couple"]) == {}


def test_unsure_blank_and_non_clock_answers_are_not_preferences() -> None:
    assert candidates(pace=["any"], wake=["any"], evening=["any"], transport=["any"]) == {}
    assert candidates() == {}
    assert candidates(wake_text=["看情况"]) == {}  # 不是可复用的时间
    assert candidates(wake=["w0830"]) == {"wake_time": ("8:30 左右", "平时几点起床：8:30 左右")}


def test_candidate_must_still_match_the_current_request() -> None:
    request, form = answered(pace=["intensive"], transport=["walk"], wake_text=["7:30"])
    changed = request.model_copy(
        update={
            "hard_constraints": ("节奏：慢节奏",),  # 用户事后在聊天里改了这次的节奏
            "transport": "taxi",
            "soft_constraints": (),
        }
    )
    assert card_candidates(form, changed) == ()  # type: ignore[arg-type]
    assert {c.key for c in card_candidates(form, request)} == {  # type: ignore[arg-type]
        "pace",
        "transport",
        "wake_time",
    }


def test_default_option_is_one_of_the_options() -> None:
    options = (
        ChoiceOption(option_id="remember", label="记住", value="remember"),
        ChoiceOption(option_id="trip", label="这次而已", value="trip"),
    )
    base = {
        "kind": "memory_confirm",
        "session_id": uuid4(),
        "source_run_id": uuid4(),
        "expected_revision": 1,
        "question": "旅行节奏：特种兵。是否保存？",
        "options": options,
    }
    card = ChoiceCard.model_validate({**base, "default_option_id": "remember"})
    assert card.model_dump(mode="json")["default_option_id"] == "remember"
    assert "default_option_id" not in ChoiceCard.model_validate(base).model_dump(mode="json")
    with pytest.raises(ValidationError):
        ChoiceCard.model_validate({**base, "default_option_id": "nope"})


def test_persona_states_the_long_term_scope_and_this_trip_rule() -> None:
    from backend.agent.persona import evaluation_judge_prompt

    text = travel_prompt()
    for phrase in (
        "住宿类型、禁烟、床型、同行、第一天几点到、最后一天几点走只对本次行程有效",
        "服务端不再询问",
        "只改本次request，不改长期偏好",
        "你没有记忆工具",
    ):
        assert phrase in text
    assert "propose_memory" not in text
    extractor = evaluation_judge_prompt("memory")
    for phrase in ("pace", "transport", "wake_time", "evening_end", "这次……”只是本次行程"):
        assert phrase in extractor

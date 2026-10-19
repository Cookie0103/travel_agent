"""合并选择卡：只含仍未定的组；答案只写用户明确选择的事实，自由文本与选项二选一。"""

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.domain.choices import (
    ChoiceCard,
    ChoiceForm,
    answered_form,
    form_patch,
    trip_ask_form,
)
from backend.domain.travel_request import TravelRequest, apply_request_patch, pace_of

ALL = (
    "pace",
    "wake",
    "evening",
    "arrival",
    "departure",
    "companion",
    "lodging",
    "smoking",
    "bed",
    "transport",
)
TRIP = TravelRequest(
    revision=4,
    city="京都",
    start_date=date(2026, 11, 20),
    end_date=date(2026, 11, 22),
    adults=2,
    child_ages=(),
    rooms=1,
)


def keys(form: ChoiceForm | None) -> tuple[str, ...]:
    return tuple(group.key for group in form.groups) if form else ()


def asked(
    request: TravelRequest = TRIP,
    tasks: tuple[str, ...] = ("itinerary",),
    memory: frozenset[str] = frozenset(),
) -> ChoiceForm | None:
    return trip_ask_form(request, tasks, memory)


def test_itinerary_asks_every_group_in_the_user_given_order() -> None:
    form = asked()
    assert form is not None and form.purpose == "trip_ask"
    assert keys(form) == ALL
    for group in form.groups:
        assert not group.required and not group.multi
        assert "any" in {option.option_id for option in group.options}
        assert 2 <= len(group.options) <= 6
    by_key = {group.key: group for group in form.groups}
    texty = ("wake", "evening", "arrival", "departure", "companion")
    assert [by_key[k].allow_text for k in texty] == [True] * 5
    assert {by_key[k].text_kind for k in texty[:4]} == {"time"}
    assert not by_key["pace"].allow_text and not by_key["transport"].allow_text
    assert [o.option_id for o in by_key["pace"].options] == [
        "relaxed",
        "standard",
        "intensive",
        "any",
    ]
    assert [o.option_id for o in by_key["transport"].options] == ["walk", "transit", "taxi", "any"]


def test_hotel_only_goal_asks_only_hotel_preferences() -> None:
    assert keys(asked(tasks=("hotel_comparison",))) == ("lodging", "smoking", "bed")


def test_day_trip_without_lodging_has_no_room_groups() -> None:
    day = TRIP.model_copy(update={"end_date": date(2026, 11, 20)})
    assert keys(asked(day)) == (
        "pace",
        "wake",
        "evening",
        "arrival",
        "departure",
        "companion",
        "transport",
    )
    assert asked(day, tasks=("hotel_comparison",)) is None


def test_known_values_are_omitted() -> None:
    request = TRIP.model_copy(
        update={
            "transport": "transit",
            "hard_constraints": (
                "节奏：特种兵",
                "11月20日下午3点抵达",
                "住宿：独立房间",
                "房型：禁烟",
                "床型：无要求",
            ),
            "soft_constraints": ("同行：情侣", "平时起床：7:30", "晚上结束：22:00"),
        }
    )
    assert keys(asked(request)) == ("departure",)
    leaving = request.model_copy(
        update={"hard_constraints": (*request.hard_constraints, "11月22日18:00离开")}
    )
    assert asked(leaving) is None


def test_confirmed_long_term_memory_only_suppresses_pace_transport_wake_evening() -> None:
    memory = frozenset({"pace", "transport", "wake_time", "evening_end", "smoking", "room_type"})
    assert keys(asked(memory=memory)) == (
        "arrival",
        "departure",
        "companion",
        "lodging",
        "smoking",
        "bed",
    )


def test_form_validation_limits() -> None:
    form = asked()
    assert form is not None
    with pytest.raises(ValidationError):
        ChoiceForm(groups=(*form.groups, *form.groups), purpose="trip_ask")  # 键重复


def test_answers_write_only_what_the_user_chose() -> None:
    form = asked()
    assert form is not None
    answers = {
        "pace": ("intensive",),
        "wake": (),
        "wake_text": ("7:30",),
        "evening": ("e2200",),
        "arrival": ("a1500",),
        "departure": ("any",),
        "companion": ("couple",),
        "lodging": ("private",),
        "smoking": ("nonsmoking",),
        "bed": ("any",),
        "transport": ("any",),
    }
    result, _ = apply_request_patch(TRIP, form_patch(TRIP, form, answers))
    assert pace_of(result) == "特种兵"
    assert result.transport == "transit"  # 标签明示“不确定（按公共交通）”，是用户确认的选择
    assert "平时起床：7:30" in result.soft_constraints
    assert any(t.startswith("晚上结束：22:00") for t in result.soft_constraints)
    assert "同行：情侣" in result.soft_constraints
    assert any(t.startswith("第一天抵达：") and "15:00" in t for t in result.hard_constraints)
    assert not any(t.startswith("最后一天离开") for t in result.hard_constraints)  # 不确定=不写
    assert {"住宿：独立房间", "房型：禁烟", "床型：无要求"} <= set(result.hard_constraints)


def test_any_on_pace_and_empty_submission_write_nothing() -> None:
    form = asked()
    assert form is not None
    result, changed = apply_request_patch(TRIP, form_patch(TRIP, form, {"pace": ("any",)}))
    assert pace_of(result) is None and result.transport is None and not changed
    result, changed = apply_request_patch(TRIP, form_patch(TRIP, form, {}))
    assert not changed and result.revision == TRIP.revision


def test_reanswer_replaces_the_same_prefix() -> None:
    form = asked()
    assert form is not None
    first, _ = apply_request_patch(
        TRIP, form_patch(TRIP, form, {"companion": ("family",), "arrival": ("a0900",)})
    )
    second, _ = apply_request_patch(
        first,
        form_patch(
            first, form, {"companion": (), "companion_text": ("和同事",), "arrival": ("a1800",)}
        ),
    )
    assert [t for t in second.soft_constraints if t.startswith("同行")] == ["同行：和同事"]
    assert len([t for t in second.hard_constraints if t.startswith("第一天抵达")]) == 1


@pytest.mark.parametrize(
    "answers",
    [
        {"wake": ("w0730",), "wake_text": ("7:30",)},  # 选项与文本二选一
        {"pace_text": ("很快",)},  # 该组不允许文本
        {"nope": ("a",)},  # 卡上没有的组
        {"pace": ("standard", "relaxed")},  # 单选
        {"pace": ("fast",)},  # 非法选项
        {"wake_text": ("",)},
        {"wake_text": ("x" * 41,)},
        {"wake_text": ("a", "b")},
    ],
)
def test_invalid_answers_are_rejected(answers: dict[str, tuple[str, ...]]) -> None:
    form = asked()
    assert form is not None
    with pytest.raises(ValueError):
        form_patch(TRIP, form, answers)


def test_answered_form_echoes_options_and_text() -> None:
    form = asked()
    assert form is not None
    done = answered_form(form, {"pace": ("standard",), "wake_text": ("7:30",)})
    by_key = {group.key: group for group in done.groups}
    assert by_key["pace"].selected == ("standard",) and by_key["pace"].text is None
    assert by_key["wake"].selected == () and by_key["wake"].text == "7:30"
    assert done.purpose == "trip_ask"


def test_hotel_assign_card_shapes() -> None:
    base = {
        "session_id": uuid4(),
        "source_run_id": uuid4(),
        "expected_revision": 1,
        "kind": "hotel_assign",
        "question": "q",
    }
    assign = {
        "hotel_name": "某酒店",
        "city": "京都",
        "check_in": "2026-11-20",
        "check_out": "2026-11-22",
        "needs_city": False,
    }
    options = [
        {"option_id": "confirm", "label": "确认", "value": "confirm"},
        {"option_id": "deny", "label": "否", "value": "deny"},
    ]
    card = ChoiceCard.model_validate({**base, "options": options, "assign": assign})
    assert card.assign is not None and card.assign.city == "京都"
    with pytest.raises(ValidationError):  # 缺少assign
        ChoiceCard.model_validate({**base, "options": options})
    wrong = [options[0], {"option_id": "x", "label": "x", "value": "x"}]
    with pytest.raises(ValidationError):  # 选项不对
        ChoiceCard.model_validate({**base, "options": wrong, "assign": assign})
    need = {**assign, "city": None, "check_in": None, "check_out": None, "needs_city": True}
    ChoiceCard.model_validate(
        {
            **base,
            "assign": need,
            "options": [
                {"option_id": "deny", "label": "填写城市", "value": "deny"},
                {"option_id": "dismiss", "label": "先不选这家", "value": "dismiss"},
            ],
        }
    )
    with pytest.raises(ValidationError):  # 普通卡不得带assign
        ChoiceCard.model_validate({**base, "kind": "pace", "options": options, "assign": assign})

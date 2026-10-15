"""点选写入规范节奏，清除两层旧别名并保留其他条件。"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.domain.choices import (
    TRANSPORT_PACE_GROUPS,
    ChoiceForm,
    ChoiceSelection,
    FormGroupInput,
    FormInput,
    answered_form,
    build_form,
    form_patch,
    legacy_form,
    pace_options,
    pace_patch,
)
from backend.domain.travel_request import TravelRequest, apply_request_patch, pace_of
from backend.persistence.models import ChoiceCardRow
from backend.services.choices import selection_prompt


@pytest.mark.parametrize("value", ["标准", "特种兵", "慢节奏"])
def test_pace_choice_replaces_hard_and_soft_aliases(value: str) -> None:
    request = TravelRequest(
        revision=7,
        hard_constraints=("禁烟", "节奏：标准节奏", "佛系"),
        soft_constraints=("甜点", "节奏：特种兵", "悠闲"),
    )
    patch = pace_patch(request, value)
    result, changed = apply_request_patch(request, patch)
    assert pace_of(result) == value
    assert result.hard_constraints == ("禁烟", f"节奏：{value}")
    assert result.soft_constraints == ("甜点",)
    assert result.revision == 8 and set(changed) == {"hard_constraints", "soft_constraints"}


def test_pace_labels_and_values_are_server_owned() -> None:
    assert [(o.option_id, o.label, o.value) for o in pace_options()] == [
        ("standard", "标准", "标准"),
        ("intensive", "特种兵", "特种兵"),
        ("relaxed", "比较轻松", "慢节奏"),
    ]
    with pytest.raises(ValueError):
        pace_patch(TravelRequest(), "模型自定义选项")


def choice_group(**overrides: object) -> dict[str, object]:
    return {
        "key": "companion",
        "label": "同行者",
        "options": [
            {"option_id": "family", "label": "带孩子"},
            {"option_id": "friends", "label": "朋友"},
        ],
        **overrides,
    }


def groups(*extra: dict[str, object]) -> tuple[FormGroupInput, ...]:
    bogus = [{"option_id": "x", "label": "瞎写"}]
    return FormInput.model_validate(
        {
            "expected_revision": 1,
            "groups": [
                {"key": "transport", "label": "交通", "options": bogus},
                {"key": "pace", "label": "节奏"},
                *extra,
            ],
        }
    ).groups


def apply(
    request: TravelRequest, form: ChoiceForm, answers: dict[str, tuple[str, ...]]
) -> TravelRequest:
    return apply_request_patch(request, form_patch(request, form, answers))[0]


BASE = {"transport": ("walk",), "pace": ("relaxed",), "companion": ("family",)}


def test_server_replaces_model_options_for_transport_and_pace() -> None:
    form = build_form(TravelRequest(), groups())
    by_key = {group.key: group for group in form.groups}
    assert [o.option_id for o in by_key["transport"].options] == ["walk", "transit", "taxi"]
    assert [o.option_id for o in by_key["pace"].options] == ["standard", "intensive", "relaxed"]
    assert not by_key["pace"].multi


@pytest.mark.parametrize(
    "bad",
    [
        [choice_group(key=f"g{i}") for i in range(5)],
        [choice_group(options=[{"option_id": f"o{i}", "label": "选"} for i in range(7)])],
        [choice_group(label="太" * 21)],
        [choice_group(options=[{"option_id": "o1", "label": "选" * 41}])],
        [choice_group(key="times")],
    ],
)
def test_form_limits_are_rejected(bad: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError):
        FormInput.model_validate({"expected_revision": 1, "groups": bad})


def test_other_group_answers_only_become_constraint_text_and_replace_on_reask() -> None:
    request = TravelRequest(revision=3, transport="walk", hard_constraints=("禁烟",))
    form = build_form(request, groups(choice_group()))
    first = apply(request, form, {**BASE, "transport": ("taxi",)})
    assert first.transport == "taxi" and pace_of(first) == "慢节奏"
    assert first.hard_constraints == ("禁烟", "节奏：慢节奏", "同行者：带孩子")
    again = apply(first, form, {**BASE, "companion": ("friends",)})
    assert again.hard_constraints == ("禁烟", "节奏：慢节奏", "同行者：朋友")
    assert again.budget == first.budget and again.adults == first.adults


@pytest.mark.parametrize(
    "answers",
    [
        {**BASE, "transport": ("plane",)},  # 未知option_id
        {**BASE, "transport": ("walk", "taxi")},  # 单选给两项
        {**BASE, "budget": ("a",)},  # 卡片没有的题目
        {**BASE, "times_corrected": ("x",)},  # 没有时间题却给更正
    ],
)
def test_invalid_answers_are_rejected(answers: dict[str, tuple[str, ...]]) -> None:
    request = TravelRequest()
    with pytest.raises(ValueError):
        form_patch(request, build_form(request, groups(choice_group())), answers)


def test_unanswered_groups_are_skipped_unless_the_model_marks_them_required() -> None:
    request = TravelRequest()
    optional = build_form(request, groups(choice_group()))
    assert apply(request, optional, {"pace": ("relaxed",)}).transport == request.transport
    required = build_form(request, groups(choice_group(required=True)))
    with pytest.raises(ValueError):
        form_patch(request, required, {"pace": ("relaxed",)})


def test_multi_group_accepts_several_and_optional_group_may_be_skipped() -> None:
    request = TravelRequest()
    form = build_form(request, groups(choice_group(multi=True, required=False)))
    both = apply(request, form, {**BASE, "companion": ("family", "friends")})
    assert "同行者：带孩子、朋友" in both.hard_constraints
    skipped = apply(request, form, {"transport": ("walk",), "pace": ("relaxed",)})
    assert not any("同行者" in text for text in skipped.hard_constraints)


def test_separate_long_time_conditions_can_be_corrected_without_truncating_other_facts() -> None:
    arrival = "11月10日09:00抵达名古屋；" + "抵达安排请保留。" * 14
    departure = "11月12日22:00离开名古屋；" + "返程安排请保留。" * 14
    request = TravelRequest(hard_constraints=("禁烟", arrival, departure, "每天08:00出发"))
    form = build_form(request, TRANSPORT_PACE_GROUPS)
    assert form.groups[-1].kind == "times" and form.groups[-1].shown == (arrival, departure)
    corrected = (arrival.replace("09:00", "10:00"), departure)
    answers: dict[str, tuple[str, ...]] = {
        "transport": ("transit",),
        "pace": ("standard",),
        "times": ("no",),
    }
    result = apply(request, form, {**answers, "times_corrected": corrected})
    assert result.hard_constraints == ("禁烟", "每天08:00出发", "节奏：标准", *corrected)
    kept = apply(request, form, {**answers, "times": ("yes",)})
    assert kept.hard_constraints == ("禁烟", arrival, departure, "每天08:00出发", "节奏：标准")
    bad_cases: list[dict[str, tuple[str, ...]]] = [
        {**answers, "times_corrected": ("  ", departure)},  # 空白更正
        {**answers, "times_corrected": ()},  # 选了不对却没写
        {**answers, "times": ("yes",), "times_corrected": corrected},  # 确认正确却混填更正
        {"transport": ("walk",), "times_corrected": corrected},  # 没答时间题却给更正
        {},  # 一题都没答
    ]
    for bad in bad_cases:
        with pytest.raises(ValueError):
            form_patch(request, form, bad)
    free = ("11月10日10点到，11月12日晚上9点走",)  # 自由文本：条数不必与原条件一致
    text = apply(request, form, {**answers, "times_corrected": free})
    assert text.hard_constraints == ("禁烟", "每天08:00出发", "节奏：标准", *free)
    only_times = apply(request, form, {"times": ("yes",)})  # 只回答一题也可提交
    assert only_times.hard_constraints == request.hard_constraints


def test_answered_form_records_selection_and_corrected_times() -> None:
    request = TravelRequest(hard_constraints=("11月10日09:00抵达",))
    form = build_form(request, TRANSPORT_PACE_GROUPS)
    done = answered_form(
        form,
        {
            "transport": ("taxi",),
            "pace": ("relaxed",),
            "times": ("no",),
            "times_corrected": ("11月10日10:00抵达",),
        },
    )
    by_key = {group.key: group for group in done.groups}
    assert by_key["transport"].selected == ("taxi",)
    assert by_key["times"].shown == ("11月10日10:00抵达",) and by_key["times"].selected == ("no",)


def test_legacy_details_selection_and_card_content_are_read_as_form() -> None:
    legacy = {
        "transport": "taxi",
        "pace": "慢节奏",
        "times_correct": False,
        "corrected_times": ["10:00抵达"],
    }
    selection = ChoiceSelection.model_validate(
        {"choice_id": str(uuid4()), "option_id": "confirm", "details": legacy}
    )
    assert selection.answers == {
        "transport": ("taxi",),
        "pace": ("relaxed",),
        "times": ("no",),
        "times_corrected": ("10:00抵达",),
    }
    assert "details" not in selection.model_dump(mode="json")
    form = legacy_form({"transport": "transit", "pace": None, "time_constraints": ["10:00抵达"]})
    by_key = {group.key: group for group in form.groups}
    assert by_key["transport"].selected == ("transit",) and by_key["pace"].selected == ()
    assert by_key["times"].shown == ("10:00抵达",)
    with pytest.raises(ValidationError):  # 旧payload缺交通同样被拒
        ChoiceSelection.model_validate(
            {"choice_id": str(uuid4()), "option_id": "confirm", "details": {"pace": "标准"}}
        )


def test_prompt_serializes_answers_with_sorted_keys() -> None:
    row = ChoiceCardRow(id=uuid4(), session_id=uuid4(), kind="form", content={})
    option = pace_options()[0]

    def prompt(answers: dict[str, tuple[str, ...]]) -> str:
        selection = ChoiceSelection(choice_id=row.id, option_id="confirm", answers=answers)
        return selection_prompt(row, option, selection)

    assert prompt({"b": ("x",), "a": ("y",)}) == prompt({"a": ("y",), "b": ("x",)})
    assert prompt({"a": ("y",), "b": ("x",)}) != prompt({"a": ("z",), "b": ("x",)})

"""点选写入规范节奏，清除两层旧别名并保留其他条件。"""

import pytest

from backend.domain.choices import (
    TravelDetailsAnswer,
    pace_options,
    pace_patch,
    travel_details,
    travel_details_patch,
)
from backend.domain.travel_request import TravelRequest, apply_request_patch, pace_of


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


def test_separate_long_time_conditions_can_be_corrected_without_truncating_other_facts() -> None:
    arrival = "11月10日09:00抵达名古屋；" + "抵达安排请保留。" * 14
    departure = "11月12日22:00离开名古屋；" + "返程安排请保留。" * 14
    request = TravelRequest(hard_constraints=("禁烟", arrival, departure, "每天08:00出发"))
    shown = travel_details(request)
    assert shown.time_constraints == (arrival, departure)
    corrected = (arrival.replace("09:00", "10:00"), departure)
    answer = TravelDetailsAnswer(
        transport="transit", pace="标准", times_correct=False, corrected_times=corrected
    )
    result, _ = apply_request_patch(request, travel_details_patch(request, shown, answer))
    assert result.hard_constraints == ("禁烟", "每天08:00出发", "节奏：标准", *corrected)
    with pytest.raises(ValueError):
        travel_details_patch(
            request, shown, answer.model_copy(update={"corrected_times": (corrected[0],)})
        )

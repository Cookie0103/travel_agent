"""服务端拥有的有界选择卡；模型只能请求类型，不能提供选项。"""

import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from backend.domain.travel_request import (
    PACE_ALIASES,
    Pace,
    RequestPatch,
    Text,
    Transport,
    TravelRequest,
    pace_of,
)

type ChoiceKind = Literal["pace", "travel_details", "budget_relaxation", "memory_confirm"]


class ChoiceOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    option_id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=200)


class TravelDetails(BaseModel):
    """卡片只展示服务端已有事实；时间保留原条件全文，不推断未知日期/时刻。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    transport_options: tuple[ChoiceOption, ...]
    pace_options: tuple[ChoiceOption, ...]
    transport: Transport | None = None
    pace: Pace | None = None
    time_constraints: tuple[Text, ...] = Field(default=(), max_length=20)


class TravelDetailsAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    transport: Transport
    pace: Pace
    times_correct: bool | None = Field(default=None, strict=True)
    corrected_times: tuple[Text, ...] | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def valid_correction(self) -> "TravelDetailsAnswer":
        if self.corrected_times is not None and any(
            not text.strip() for text in self.corrected_times
        ):
            raise ValueError("更正时间不能为空白")
        if (self.times_correct is False) != (self.corrected_times is not None):
            raise ValueError("时间不正确时必须填写更正；确认正确时不能混填更正")
        return self


class ChoiceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    choice_id: UUID
    option_id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")
    details: TravelDetailsAnswer | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class ChoiceCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    choice_id: UUID = Field(default_factory=uuid4)
    kind: ChoiceKind
    session_id: UUID
    source_run_id: UUID
    expected_revision: int = Field(strict=True, ge=0)
    question: str = Field(min_length=1, max_length=200)
    options: tuple[ChoiceOption, ...] = Field(min_length=1, max_length=3)
    details: TravelDetails | None = Field(default=None, exclude_if=lambda value: value is None)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: AwareDatetime | None = None
    answered_option_id: str | None = None
    stale: bool = False

    @model_validator(mode="after")
    def valid_options(self) -> "ChoiceCard":
        if self.kind == "travel_details":
            if (
                self.details is None
                or len(self.options) != 1
                or self.options[0].option_id != "confirm"
            ):
                raise ValueError("旅行条件卡需要组合选项和统一确认操作")
        elif self.details is not None or len(self.options) < 2:
            raise ValueError("普通选择卡需要2至3个选项，不能混入旅行条件")
        ids = {option.option_id for option in self.options}
        if len(ids) != len(self.options) or (
            self.answered_option_id is not None and self.answered_option_id not in ids
        ):
            raise ValueError("选择卡的选项或已选值不匹配")
        return self


def pace_options() -> tuple[ChoiceOption, ...]:
    return tuple(
        ChoiceOption(option_id=option_id, label=label, value=value)
        for option_id, label, value in (
            ("standard", "标准", "标准"),
            ("intensive", "特种兵", "特种兵"),
            ("relaxed", "比较轻松", "慢节奏"),
        )
    )


def pace_patch(request: TravelRequest, value: str) -> RequestPatch:
    if value not in {option.value for option in pace_options()}:
        raise ValueError("无效节奏选项")

    def keep_other(values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            text for text in values if text.removeprefix("节奏：").strip() not in PACE_ALIASES
        )

    return RequestPatch.model_validate(
        {
            "expected_revision": request.revision,
            "set": {
                "hard_constraints": (*keep_other(request.hard_constraints), f"节奏：{value}"),
                "soft_constraints": keep_other(request.soft_constraints),
            },
        }
    )


def travel_details(request: TravelRequest) -> TravelDetails:
    # 不变量：这是显示已有条件，不从模型回答或网页猜时间；编辑时展示/替换同一完整条件。
    times = tuple(
        text
        for text in request.hard_constraints
        if re.search(r"抵达|到达|返程|离开|返回|回程|出发", text)
        and re.search(r"\d[:：]\d{2}|\d\s*[点時时]", text)
        and not re.search(r"每天|每日", text)
    )
    return TravelDetails(
        transport_options=tuple(
            ChoiceOption(option_id=value, label=label, value=value)
            for value, label in (
                ("walk", "步行"),
                ("transit", "公共交通（公交、地铁为主）"),
                ("taxi", "打车"),
            )
        ),
        pace_options=pace_options(),
        transport=request.transport,
        pace=pace_of(request),
        time_constraints=times,
    )


def travel_details_patch(
    request: TravelRequest, card: TravelDetails, answer: TravelDetailsAnswer
) -> RequestPatch:
    if bool(card.time_constraints) != (answer.times_correct is not None):
        raise ValueError("请确认卡中已有的抵达/离开时间；没有时间提议时不能混填确认")
    patch = pace_patch(request, answer.pace)
    hard = patch.set_fields.hard_constraints
    if answer.times_correct is False:
        hard = tuple(text for text in hard if text not in card.time_constraints)
        assert answer.corrected_times is not None
        if len(answer.corrected_times) != len(card.time_constraints):
            raise ValueError("请逐条更正时间安排，保留未修改的部分")
        hard = (*hard, *(text.strip() for text in answer.corrected_times))
    return RequestPatch.model_validate(
        {
            "expected_revision": request.revision,
            "set": {
                "transport": answer.transport,
                "hard_constraints": hard,
                "soft_constraints": patch.set_fields.soft_constraints,
            },
        }
    )

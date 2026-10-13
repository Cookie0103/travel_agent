"""服务端拥有的有界选择卡；模型只能请求类型，不能提供选项。"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from backend.domain.travel_request import PACE_ALIASES, RequestPatch, TravelRequest

type ChoiceKind = Literal["pace", "budget_relaxation", "memory_confirm"]


class ChoiceOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    option_id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=200)


class ChoiceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    choice_id: UUID
    option_id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")


class ChoiceCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    choice_id: UUID = Field(default_factory=uuid4)
    kind: ChoiceKind
    session_id: UUID
    source_run_id: UUID
    expected_revision: int = Field(strict=True, ge=0)
    question: str = Field(min_length=1, max_length=200)
    options: tuple[ChoiceOption, ...] = Field(min_length=2, max_length=3)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: AwareDatetime | None = None
    answered_option_id: str | None = None
    stale: bool = False

    @model_validator(mode="after")
    def valid_options(self) -> "ChoiceCard":
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

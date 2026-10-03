"""旅行条件与set/clear更新规则；服务在数据库锁内调用，模型不能绕过版本检查。"""

from datetime import date, time
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Age = Annotated[int, Field(strict=True, ge=0, le=17)]
Text = Annotated[str, Field(min_length=1, max_length=200)]
Transport = Literal["walk", "transit", "taxi"]


class TravelConditions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    city: Literal["京都"] | None = None
    start_date: date | None = None
    end_date: date | None = None
    timezone: Literal["Asia/Tokyo"] = "Asia/Tokyo"
    adults: int | None = Field(default=None, strict=True, ge=1, le=12)
    child_ages: tuple[Age, ...] | None = Field(default=None, max_length=8)
    rooms: int | None = Field(default=None, strict=True, ge=1, le=6)
    budget: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: Literal["JPY"] = "JPY"
    transport: Transport | None = None
    departure_time: time | None = None
    interests: tuple[Text, ...] = Field(default=(), max_length=20)
    hard_constraints: tuple[Text, ...] = Field(default=(), max_length=20)
    soft_constraints: tuple[Text, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def valid_dates(self) -> Self:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("旅行结束日期不能早于开始日期")
        if self.departure_time and self.departure_time.tzinfo is not None:
            raise ValueError("出发时刻使用旅行时区的本地时间，不接受另一时区")
        return self


class TravelRequest(TravelConditions):
    revision: int = Field(default=0, strict=True, ge=0)

    def hotel_requirements(self) -> tuple[str, ...]:
        required = ("city", "start_date", "end_date", "adults", "child_ages", "rooms")
        missing = tuple(name for name in required if getattr(self, name) is None)
        # 当天往返是合法旅行；只有酒店报价要求至少一晚。
        if self.start_date and self.end_date and self.end_date == self.start_date:
            return (*missing, "overnight_stay")
        return missing


class RequestPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_revision: int = Field(strict=True, ge=0)
    set_fields: TravelConditions = Field(default_factory=TravelConditions, alias="set")
    clear: tuple[str, ...] = Field(default=(), max_length=14)

    @model_validator(mode="after")
    def valid_operations(self) -> Self:
        if set(self.clear) - TravelConditions.model_fields.keys():
            raise ValueError("clear包含未知字段")
        if set(self.clear) & self.set_fields.model_fields_set:
            raise ValueError("同一字段不能同时set和clear")
        if any(getattr(self.set_fields, name) is None for name in self.set_fields.model_fields_set):
            raise ValueError("清除字段请使用clear，不以null代替")
        return self


class RequestConflict(ValueError):
    """由服务转换为conflict；不通过重试覆盖用户的新条件。"""


def apply_request_patch(
    current: TravelRequest, patch: RequestPatch
) -> tuple[TravelRequest, frozenset[str]]:
    if current.revision != patch.expected_revision:
        raise RequestConflict("旅行条件版本已变化，请读取最新条件")
    data = current.model_dump()
    data.update(patch.set_fields.model_dump(exclude_unset=True))
    defaults = TravelConditions().model_dump()
    data.update({name: defaults[name] for name in patch.clear})
    updated = TravelRequest.model_validate(data)
    changed = frozenset(
        name
        for name in TravelConditions.model_fields
        if getattr(current, name) != getattr(updated, name)
    )
    return updated.model_copy(update={"revision": current.revision + bool(changed)}), changed


def invalidated_kinds(changed: frozenset[str]) -> frozenset[str]:
    kinds: set[str] = set()
    if changed & {"city", "start_date", "end_date", "adults", "child_ages", "rooms", "currency"}:
        kinds.add("hotel_offer")
    if changed & {"city", "start_date", "end_date", "transport", "departure_time"}:
        kinds.add("route")
    return frozenset(kinds)

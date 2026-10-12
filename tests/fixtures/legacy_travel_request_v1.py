"""冻结的b6fa30b旧条件模型，仅用于增量迁移/快照兼容回归；不随新字段更新。"""

from datetime import date, time
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Age = Annotated[int, Field(strict=True, ge=0, le=17)]
Text = Annotated[str, Field(min_length=1, max_length=200)]
Transport = Literal["walk", "transit", "taxi"]


class TravelConditions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    city: str | None = Field(default=None, min_length=1, max_length=40)
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

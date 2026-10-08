"""旅行条件与set/clear更新规则；服务在数据库锁内调用，模型不能绕过版本检查。"""

from datetime import date, time
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Age = Annotated[int, Field(strict=True, ge=0, le=17)]
Text = Annotated[str, Field(min_length=1, max_length=200)]
Transport = Literal["walk", "transit", "taxi"]


BudgetAmount = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]


class BudgetRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    lower: BudgetAmount | None = None
    upper: BudgetAmount | None = None

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if self.lower is None and self.upper is None:
            raise ValueError("住宿预算至少需要一个金额端点")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("住宿预算下限不能大于上限")
        return self


class LodgingBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    amount: BudgetRange
    basis: Literal["per_room_night", "total"]
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class BudgetRelation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["conflict", "warning", "unknown", "within"]
    total_lower: Decimal | None = None
    total_upper: Decimal | None = None
    currency: str | None = None
    message: str


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
    lodging_budget: LodgingBudget | None = None
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


class LegacyRequestSnapshot(TravelRequest):
    """明确的旧快照输出类型，保留schema类型但不序列化新增预算。"""

    lodging_budget: LodgingBudget | None = Field(default=None, exclude=True)


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


def lodging_budget_relation(request: TravelRequest) -> BudgetRelation:
    """唯一预算关系计算：保留原值，只换算已知房晚、不换汇。"""
    lodging = request.lodging_budget
    if lodging is None:
        return BudgetRelation(status="unknown", message="住宿预算未知；不会按全程预算自动分配。")
    if lodging.basis == "per_room_night":
        if request.rooms is None or request.start_date is None or request.end_date is None:
            return BudgetRelation(
                status="unknown",
                currency=lodging.currency,
                message="房间数或晚数未知，无法判断住宿预算总额；请补充。",
            )
        units = request.rooms * (request.end_date - request.start_date).days
    else:
        units = 1
    lower = lodging.amount.lower * units if lodging.amount.lower is not None else None
    upper = lodging.amount.upper * units if lodging.amount.upper is not None else None
    if request.budget is None or lodging.currency != request.currency:
        return BudgetRelation(
            total_lower=lower,
            total_upper=upper,
            currency=lodging.currency,
            status="unknown",
            message="全程预算未知或两个预算币种不同，无法判断；不估算、不换汇。",
        )
    if lower is not None and lower > request.budget:
        return BudgetRelation(
            total_lower=lower,
            total_upper=upper,
            currency=lodging.currency,
            status="conflict",
            message=(
                f"住宿预算总额下限{lower} {lodging.currency}超过全程预算"
                f"{request.budget} {request.currency}。请确认以哪个预算为准；"
                "解决前不能比较酒店或确认草稿。"
            ),
        )
    if upper is not None and upper > request.budget:
        return BudgetRelation(
            total_lower=lower,
            total_upper=upper,
            currency=lodging.currency,
            status="warning",
            message=(
                f"预算警告：住宿总额上限{upper} {lodging.currency}可能超过全程预算"
                f"{request.budget} {request.currency}；原值均保留，请确认可接受范围。"
            ),
        )
    if upper is None:
        return BudgetRelation(
            total_lower=lower,
            total_upper=upper,
            currency=lodging.currency,
            status="unknown",
            message="住宿预算总额上限未知，无法完整判断；不会补成零。",
        )
    return BudgetRelation(
        total_lower=lower,
        total_upper=upper,
        currency=lodging.currency,
        status="within",
        message="住宿预算上限未超过全程预算；其他旅行费用仍需核实。",
    )


def legacy_request(request: TravelRequest) -> dict[str, object]:
    """旧版本可读取的快照，新增预算唯一持久位置为request_details。"""
    return request.model_dump(mode="json", exclude={"lodging_budget"})

"""旅行条件与set/clear更新规则；服务在数据库锁内调用，模型不能绕过版本检查。"""

from datetime import date, time
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.domain.external_data import broad_region
from backend.domain.room_choices import (
    ROOM_CHOICES,
    RoomPreferencesPatch,
    normalize_room_choices,
    recognized_room_choices,
)

Age = Annotated[int, Field(strict=True, ge=0, le=17)]
Text = Annotated[str, Field(min_length=1, max_length=200)]
Transport = Literal["walk", "transit", "taxi"]
ConditionSource = Literal["conversation", "user_form", "none"]


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


class TripSegment(BaseModel):
    """一个城市的连续停留；住宿晚数由离开日期减到达日期得出。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    city: str = Field(min_length=1, max_length=40)
    arrive: date
    depart: date
    hotel_search_location: str | None = Field(
        default=None, min_length=1, max_length=40, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def valid_dates(self) -> Self:
        if self.depart < self.arrive:
            raise ValueError("城市段离开日期不能早于到达日期")
        return self


Segments = Annotated[tuple[TripSegment, ...] | None, Field(min_length=2, max_length=6)]


class TravelConditions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    city: str | None = Field(default=None, min_length=1, max_length=40)
    hotel_search_location: str | None = Field(
        default=None,
        min_length=1,
        max_length=40,
        description="用户明确指定的住宿查询城市或地点，保留旅行city不变；省级范围须进一步细化",
    )
    start_date: date | None = None
    end_date: date | None = None
    timezone: Literal["Asia/Tokyo"] = "Asia/Tokyo"
    adults: int | None = Field(default=None, strict=True, ge=1, le=12)
    child_ages: tuple[Age, ...] | None = Field(default=None, max_length=8)
    rooms: int | None = Field(default=None, strict=True, ge=1, le=6)
    budget: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: Literal["JPY"] = "JPY"
    lodging_budget: LodgingBudget | None = None
    segments: Segments = None
    lodging_budget_unlimited: bool = Field(default=False, strict=True)
    transport: Transport | None = None
    departure_time: time | None = Field(
        default=None,
        description=(
            "每天开始游玩的当地时间，仅在用户明确每日出发时设置。不是首日抵达时间、"
            "末日返程或航班/车次时间；这些带日期和角色写入hard_constraints。"
            "未说明每日出发时不要填；用户明确纠正旧误填时清除此字段。"
        ),
    )
    interests: tuple[Text, ...] = Field(default=(), max_length=20)
    hard_constraints: tuple[Text, ...] = Field(default=(), max_length=20)
    soft_constraints: tuple[Text, ...] = Field(default=(), max_length=20)

    @field_validator("hard_constraints")
    @classmethod
    def canonical_room_choices(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return normalize_room_choices(value)

    @model_validator(mode="after")
    def valid_dates(self) -> Self:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("旅行结束日期不能早于开始日期")
        if self.departure_time and self.departure_time.tzinfo is not None:
            raise ValueError("出发时刻使用旅行时区的本地时间，不接受另一时区")
        if self.lodging_budget is not None and self.lodging_budget_unlimited:
            raise ValueError("住宿预算金额与明确不限不能同时设置，请清除另一项")
        if self.segments:
            for index, segment in enumerate(self.segments):
                if index < len(self.segments) - 1 and segment.depart == segment.arrive:
                    raise ValueError("只有最后一个城市段允许零晚住宿")
                if index and segment.arrive != self.segments[index - 1].depart:
                    raise ValueError("城市段必须连续，不能重叠或留下日期缺口")
            expected = {
                "city": self.segments[0].city,
                "start_date": self.segments[0].arrive,
                "end_date": self.segments[-1].depart,
            }
            for name, value in expected.items():
                if getattr(self, name) is not None and getattr(self, name) != value:
                    raise ValueError("全局城市与首末日期必须和城市段一致")
        return self


# 酒店查询必需条件 -> 面向用户的固定中文名；顺序即展示顺序，未列出的字段一律不展示。
HOTEL_FIELD_LABELS: dict[str, str] = {
    "city": "目的地",
    "start_date": "入住日期",
    "end_date": "退房日期",
    "adults": "成人人数",
    "child_ages": "儿童年龄",
    "rooms": "房间数",
    "overnight_stay": "至少住一晚",
}


class TravelRequest(TravelConditions):
    revision: int = Field(default=0, strict=True, ge=0)
    # 响应/持久内容省略空增量；patch输入不能省略明确的False，否则会丢清除操作。
    segments: Segments = Field(default=None, exclude_if=lambda value: value is None)
    lodging_budget_unlimited: bool = Field(
        default=False, strict=True, exclude_if=lambda value: not value
    )

    @model_validator(mode="after")
    def segment_globals_required(self) -> Self:
        if self.segments and (
            self.city is None or self.start_date is None or self.end_date is None
        ):
            raise ValueError("完整旅行条件必须包含城市段派生的城市与首末日期")
        return self

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
    hotel_search_location: str | None = Field(default=None, exclude=True)
    segments: tuple[TripSegment, ...] | None = Field(default=None, exclude=True)
    lodging_budget_unlimited: bool = Field(default=False, exclude=True)


class RequestPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_revision: int = Field(strict=True, ge=0)
    set_fields: TravelConditions = Field(default_factory=TravelConditions, alias="set")
    clear: tuple[str, ...] = Field(default=(), max_length=14)

    @model_validator(mode="after")
    def valid_operations(self) -> Self:
        if set(self.clear) - TravelConditions.model_fields.keys():
            raise ValueError("clear包含未知字段")
        if self.set_fields.segments and set(self.clear) & {"city", "start_date", "end_date"}:
            raise ValueError("设置城市段时不能同时清除其派生的城市或首末日期")
        if set(self.clear) & self.set_fields.model_fields_set:
            raise ValueError("同一字段不能同时set和clear")
        if any(getattr(self.set_fields, name) is None for name in self.set_fields.model_fields_set):
            raise ValueError("清除字段请使用clear，不以null代替")
        return self


class RequestConflict(ValueError):
    """由服务转换为conflict；不通过重试覆盖用户的新条件。"""


class ConversationRequestPatch(RequestPatch):
    explicit_fields: tuple[str, ...] = Field(
        default=(),
        max_length=15,
        description="本次明确改变的set/clear字段名；room_preferences投影为hard_constraints，填['hard_constraints']，不是bed或room_preferences",
    )
    remove_hard_constraints: tuple[Text, ...] = Field(default=(), max_length=20)
    room_preferences: RoomPreferencesPatch | None = Field(
        default=None, description="只提供本轮明确的房型组；未提组省略，不能填null；无要求用any"
    )

    @model_validator(mode="before")
    @classmethod
    def project_room_preferences(cls, data: object) -> object:
        if not isinstance(data, dict) or data.get("room_preferences") is None:
            return data
        room = RoomPreferencesPatch.model_validate(data["room_preferences"])
        fields = data.get("set", {})
        if not isinstance(fields, dict):
            raise ValueError("set必须是字段对象")
        texts = fields.get("hard_constraints", [])
        if not isinstance(texts, (list, tuple)) or any(
            not isinstance(value, str) for value in texts
        ):
            raise ValueError("hard_constraints必须是文本列表")
        incoming = recognized_room_choices(tuple(texts))
        for choice in room.constraints():
            group = next(values for values in ROOM_CHOICES.values() if choice in values)
            if (incoming & group) - {choice}:
                raise ValueError("room_preferences与硬条件房型组矛盾，请修正参数")
        choices = [choice for choice in room.constraints() if choice not in incoming]
        return {**data, "set": {**fields, "hard_constraints": [*texts, *choices]}}

    @model_validator(mode="after")
    def explicit_subset(self) -> Self:
        if self.remove_hard_constraints and (
            "hard_constraints" not in self.explicit_fields
            or "hard_constraints" not in self.set_fields.model_fields_set
        ):
            raise ValueError("删除硬条件必须明确声明hard_constraints并提供set")
        if set(self.explicit_fields) - (self.set_fields.model_fields_set | set(self.clear)):
            raise ValueError("explicit_fields必须是本次set/clear字段的子集")
        return self


def apply_request_patch(
    current: TravelRequest, patch: RequestPatch
) -> tuple[TravelRequest, frozenset[str]]:
    if current.revision != patch.expected_revision:
        raise RequestConflict("旅行条件版本已变化，请读取最新条件")
    data = current.model_dump()
    data.update(patch.set_fields.model_dump(exclude_unset=True))
    empty = TravelConditions()
    defaults = {name: getattr(empty, name) for name in TravelConditions.model_fields}
    data.update({name: defaults[name] for name in patch.clear})
    if "segments" in patch.set_fields.model_fields_set and patch.set_fields.segments:
        segments = patch.set_fields.segments
        data.update(
            city=segments[0].city,
            start_date=segments[0].arrive,
            end_date=segments[-1].depart,
        )
    if (
        data["city"] != current.city
        and "hotel_search_location" not in patch.set_fields.model_fields_set
    ):
        data["hotel_search_location"] = None
    updated = TravelRequest.model_validate(data)
    changed = frozenset(
        name
        for name in TravelConditions.model_fields
        if getattr(current, name) != getattr(updated, name)
    )
    return updated.model_copy(update={"revision": current.revision + bool(changed)}), changed


def invalidated_kinds(changed: frozenset[str]) -> frozenset[str]:
    kinds: set[str] = set()
    if changed & {
        "city",
        "hotel_search_location",
        "start_date",
        "end_date",
        "adults",
        "child_ages",
        "rooms",
        "currency",
        "segments",
    }:
        kinds.add("hotel_offer")
    if changed & {"city", "start_date", "end_date", "transport", "departure_time", "segments"}:
        kinds.add("route")
    return frozenset(kinds)


def trip_segments(request: TravelRequest) -> tuple[TripSegment, ...]:
    """旧单城市统一派生入口；未齐城市/日期的条件没有可查询城市段。"""
    if request.segments is not None:
        return request.segments
    if request.city is None or request.start_date is None or request.end_date is None:
        return ()
    return (
        TripSegment(
            city=request.city,
            arrive=request.start_date,
            depart=request.end_date,
            hotel_search_location=request.hotel_search_location,
        ),
    )


def segment_request(request: TravelRequest, segment: TripSegment) -> TravelRequest:
    """酒店查询/证据专用内存副本；不得替代会话的持久旅行条件。"""
    return request.model_copy(
        update={
            "city": segment.city,
            "start_date": segment.arrive,
            "end_date": segment.depart,
            "hotel_search_location": segment.hotel_search_location,
            "segments": None,
        }
    )


def cities_on(request: TravelRequest, day: date) -> set[str]:
    return {
        segment.city
        for segment in trip_segments(request)
        if segment.arrive <= day <= segment.depart
    }


Pace = Literal["标准", "慢节奏", "特种兵"]
PACE_ALIASES: dict[str, Pace] = {
    "标准": "标准",
    "标准节奏": "标准",
    "正常": "标准",
    "慢节奏": "慢节奏",
    "轻松": "慢节奏",
    "佛系": "慢节奏",
    "悠闲": "慢节奏",
    "特种兵": "特种兵",
}


def pace_of(request: TravelRequest) -> Pace | None:
    """仅识别确认过的规范值及有限别名，硬条件优先，不推测任意自由文本。"""
    for text in (*request.hard_constraints, *request.soft_constraints):
        pace = PACE_ALIASES.get(text.removeprefix("节奏：").strip())
        if pace:
            return pace
    return None


CITY_ALIASES = {
    "kyoto": "京都",
    "osaka": "大阪",
    "kobe": "神戸",
    "神户": "神戸",
    "nara": "奈良",
    "tokyo": "東京",
    "东京": "東京",
    "sapporo": "札幌",
    "hakone": "箱根",
    "okinawa": "沖縄",
    "冲绳": "沖縄",
    "naha": "那覇",
    "那霸": "那覇",
}


def same_city(a: str, b: str) -> bool:
    """只统一本项目已有城市的有限别名，不引入地名推断。"""
    normalized = ["".join(value.split()).casefold().removesuffix("市") for value in (a, b)]
    return CITY_ALIASES.get(normalized[0], normalized[0]) == CITY_ALIASES.get(
        normalized[1], normalized[1]
    )


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
    return request.model_dump(
        mode="json",
        exclude={"lodging_budget", "hotel_search_location", "segments", "lodging_budget_unlimited"},
    )


def hotel_search_location_required(request: TravelRequest) -> bool:
    location = request.hotel_search_location or request.city
    return bool(location and broad_region(location))

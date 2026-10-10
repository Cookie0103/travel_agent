"""行程草案、路线与校验结果契约；模型提供安排与证据引用，事实由服务端补齐。"""

from datetime import date
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    model_validator,
)

PLAN_ITEM_LIMIT = 200


class HotelStay(BaseModel):
    """住宿段日期与报价引用；段范围及报价条件由行程validator核验。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    check_in: date
    check_out: date
    hotel_evidence_id: UUID


class ProposedItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    place_evidence_id: UUID = Field(
        description="仅用search_places/get_place_facts返回的kind=place的evidence_id；"
        "不是place_id，也不能用酒店报价或route证据ID"
    )
    start: AwareDatetime = Field(description="含时区的ISO时间；日本时间使用+09:00")
    end: AwareDatetime = Field(description="含时区的ISO时间；日本时间使用+09:00")
    route_evidence_id: UUID | None = Field(
        default=None,
        description="本项的入站路段：仅用estimate_routes返回的kind=route的evidence_id，"
        "起点须为同一天前一景点、终点须为本景点；每天首项必须省略。"
        "不要把出站路段挂到前一项，不用route_id代替evidence_id",
    )
    note: str | None = Field(
        default=None, max_length=80, description="一句话概述，模型撰写，非来源核实"
    )


class ItineraryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: int = Field(strict=True, ge=0)
    items: tuple[ProposedItem, ...] = Field(min_length=1, max_length=PLAN_ITEM_LIMIT)
    hotel_evidence_id: UUID | None = Field(
        default=None,
        description="酒店卡片(search_hotel_offers)的evidence_id，不是offer_id；无卡片则省略",
    )
    hotel_stays: tuple[HotelStay, ...] = Field(
        default=(),
        max_length=6,
        exclude_if=lambda value: not value,
    )

    @model_validator(mode="after")
    def exclusive_hotels(self) -> Self:
        if self.hotel_evidence_id is not None and self.hotel_stays:
            raise ValueError("旧酒店引用与分段住宿不能同时设置")
        return self

    def evidence_ids(self) -> tuple[UUID, ...]:
        ids = [item.place_evidence_id for item in self.items]
        ids.extend(item.route_evidence_id for item in self.items if item.route_evidence_id)
        if self.hotel_evidence_id:
            ids.append(self.hotel_evidence_id)
        ids.extend(stay.hotel_evidence_id for stay in self.hotel_stays)
        return tuple(dict.fromkeys(ids))


class RouteLeg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    from_evidence_id: UUID = Field(
        description="前一个景点的kind=place的evidence_id（search_places/get_place_facts返回）；"
        "不是place_id，不接受酒店报价、文章或route证据ID"
    )
    to_evidence_id: UUID = Field(
        description="同一天后一个景点的kind=place的evidence_id（search_places/get_place_facts返回）；"
        "不是place_id，不接受酒店报价、文章或route证据ID"
    )
    departure: AwareDatetime = Field(
        description=(
            "含时区的ISO出发时间，日本时间用+09:00；必须落在前一项结束时间与后一项开始时间之间，"
            "通常直接用前一项的结束时间，不要统一填默认时间"
        )
    )


class RouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: int = Field(strict=True, ge=0)
    legs: tuple[RouteLeg, ...] = Field(min_length=1, max_length=6)


class RouteEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    route_id: UUID = Field(default_factory=uuid4)
    from_place_id: str
    to_place_id: str
    transport: Literal["walk", "transit", "taxi"]
    departure: AwareDatetime
    minutes: int | None = Field(default=None, strict=True, ge=0, le=1440)
    fare: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: Literal["JPY"] = "JPY"
    fare_scope: Literal["party_estimate"] = "party_estimate"
    confidence: Literal["estimate", "unknown"]

    @model_validator(mode="after")
    def estimate_has_duration(self) -> Self:
        if self.confidence == "estimate" and self.minutes is None:
            raise ValueError("估算路段需要耗时，缺失应标unknown")
        if self.confidence == "unknown" and (self.minutes is not None or self.fare is not None):
            raise ValueError("未覆盖的路段不能提供假定耗时或费用")
        return self


CheckStatus = Literal["verified", "unknown", "conflict"]


class ValidationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    subject: str
    status: CheckStatus
    code: str
    message: str
    _trace: str | None = PrivateAttr(default=None)  # 仅TRACE用的安全位置/时间标签，不进API

    def tagged(self, label: str) -> "ValidationCheck":
        self._trace = label
        return self

    @property
    def trace_label(self) -> str:
        return self._trace or f"{self.code}:{self.status}"


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["complete", "partial", "conflict"]
    checks: tuple[ValidationCheck, ...]
    known_cost: Decimal
    estimated_cost: Decimal
    scope: str = "按当前来源与报价校验；路线时长为估算，临时闭馆与未核实费用仍需出行前确认"

    def feedback(self) -> dict[str, object]:
        ordered = sorted(
            self.checks,
            key=lambda check: (
                {"conflict": 0, "unknown": 1, "verified": 2}[check.status],
                check.code not in ("pace_warning", "repeated_place_warning"),
            ),
        )
        return {
            **self.model_dump(mode="json", exclude={"checks"}),
            "checks": [check.model_dump(mode="json") for check in ordered[:12]],
            "check_counts": {
                state: sum(check.status == state for check in self.checks)
                for state in ("verified", "unknown", "conflict")
            },
            "truncated": len(ordered) > 12,
        }

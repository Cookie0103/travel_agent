"""行程草案、路线与校验结果契约；模型提供安排与证据引用，事实由服务端补齐。"""

from decimal import Decimal
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ProposedItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    place_evidence_id: UUID
    start: AwareDatetime = Field(description="含时区的ISO时间；日本时间使用+09:00")
    end: AwareDatetime = Field(description="含时区的ISO时间；日本时间使用+09:00")
    route_evidence_id: UUID | None = None
    note: str | None = Field(
        default=None, max_length=80, description="一句话概述，模型撰写，非来源核实"
    )


class ItineraryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: int = Field(strict=True, ge=0)
    items: tuple[ProposedItem, ...] = Field(min_length=1, max_length=24)
    hotel_evidence_id: UUID | None = None

    def evidence_ids(self) -> tuple[UUID, ...]:
        ids = [item.place_evidence_id for item in self.items]
        ids.extend(item.route_evidence_id for item in self.items if item.route_evidence_id)
        if self.hotel_evidence_id:
            ids.append(self.hotel_evidence_id)
        return tuple(dict.fromkeys(ids))


class RouteLeg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    from_evidence_id: UUID
    to_evidence_id: UUID
    departure: AwareDatetime = Field(description="含时区的ISO出发时间；日本时间使用+09:00")


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
            key=lambda check: {"conflict": 0, "unknown": 1, "verified": 2}[check.status],
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

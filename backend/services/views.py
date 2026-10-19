"""工作台输出契约；复用领域对象，只描述服务端补齐的卡片，不计算业务规则。"""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from backend.domain.external_data import DataMode
from backend.domain.hotel_details import HotelDisplayDetails
from backend.domain.hotel_recovery import HotelSearchDiagnostics
from backend.domain.hotels import QuoteFields
from backend.domain.itinerary import HotelStay, ValidationReport
from backend.domain.plans import ItemDiff, PlanItem
from backend.domain.travel_request import (
    BudgetRelation,
    ConditionSource,
    TravelRequest,
    lodging_budget_relation,
)


class RequestView(TravelRequest):
    budget_relation: BudgetRelation
    field_sources: dict[str, ConditionSource] = Field(default_factory=dict)

    @classmethod
    def from_request(
        cls, request: TravelRequest, field_sources: dict[str, ConditionSource] | None = None
    ) -> "RequestView":
        return cls.model_validate(
            {
                **request.model_dump(),
                "budget_relation": lodging_budget_relation(request),
                "field_sources": field_sources or {},
            }
        )


class HotelCard(QuoteFields, HotelDisplayDetails):
    model_config = ConfigDict(json_schema_serialization_defaults_required=False)
    offer_id: UUID
    room_tags: tuple[str, ...] = ()
    qualification_unknown: bool = False
    room_preference_mismatch: bool = False
    stay: dict[str, object]
    request_revision: int
    total: str | None
    lodging_exceeds_trip_budget: bool | None
    lodging_exceeds_lodging_budget: bool | None = None
    data_mode: Literal["fixture", "live", "synthetic"]
    evidence_id: UUID
    source_ref: str | None
    content_version: str | None
    budget_excess: str | None = Field(
        default_factory=lambda: None, exclude_if=lambda value: value is None
    )
    budget_excess_percent: str | None = Field(
        default_factory=lambda: None, exclude_if=lambda value: value is None
    )


class ValidationFeedback(ValidationReport):
    check_counts: dict[str, int]
    truncated: bool


class PlanCard(PlanItem):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    name: str
    source_ref: str | None
    data_mode: DataMode
    city: str | None = Field(default=None, exclude_if=lambda value: value is None)


class HotelStayView(HotelStay):
    hotel: HotelCard | None = None


class PlanView(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    plan_id: UUID
    request_revision: int
    cards: tuple[PlanCard, ...]
    hotel: HotelCard | None
    hotel_evidence_id: UUID | None
    hotel_stays: tuple[HotelStayView, ...] = Field(default=(), exclude_if=lambda value: not value)
    needs_refresh: tuple[UUID, ...]
    validation: ValidationFeedback
    guidance: str
    version: int | None = None
    saved_at: AwareDatetime | None = None
    historical: bool = False
    draft_id: UUID | None = None
    base_version: int | None = None
    changes: tuple[ItemDiff, ...] = ()
    hotel_changed: bool = False
    expires_at: AwareDatetime | None = None
    status: Literal["staged", "confirmed"] | None = None
    expired: bool = False
    conditions_changed: bool = False
    version_changed: bool = False


class Comparison(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=False)
    room_preferences_question: str | None = None
    budget_relation: BudgetRelation | None = None
    comparable: bool
    reasons: tuple[str, ...]
    lowest_offer_ids: tuple[UUID, ...]
    scope: str
    search_url: str | None = Field(
        default_factory=lambda: None, exclude_if=lambda value: value is None
    )


class HotelSegmentPresentation(BaseModel):
    city: str
    check_in: date
    check_out: date
    evidence_ids: tuple[UUID, ...]
    comparison: Comparison
    total_found: int | None = None
    more_url: str | None = None
    more_url_scope: Literal["search", "destination"] | None = None
    relaxation: HotelSearchDiagnostics | None = Field(
        default_factory=lambda: None, exclude_if=lambda value: value is None
    )


class HotelPresentation(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=False)
    component: Literal["hotel_comparison"]
    cards: tuple[HotelCard, ...]
    segments: tuple[HotelSegmentPresentation, ...] = Field(
        default_factory=tuple, exclude_if=lambda value: not value
    )
    comparison: Comparison
    total_found: int | None = None
    more_url: str | None = None
    more_url_scope: Literal["search", "destination"] | None = None
    relaxation: HotelSearchDiagnostics | None = Field(
        default_factory=lambda: None, exclude_if=lambda value: value is None
    )


class HotelSelectionPick(BaseModel):
    evidence_id: UUID
    hotel_name: str
    source: Literal["button", "chat", "assign_confirm"]


class HotelSelectionSegment(BaseModel):
    city: str
    check_in: date
    check_out: date
    selected: HotelSelectionPick | None = None


class HotelSelectionView(BaseModel):
    """酒店面板状态：单城市也是一个住宿段；can_skip时面板显示“先不选酒店，先排行程”。"""

    state: Literal["not_applicable", "awaiting", "complete", "skipped"]
    segments: tuple[HotelSelectionSegment, ...]
    can_skip: bool

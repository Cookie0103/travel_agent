"""工作台输出契约；复用领域对象，只描述服务端补齐的卡片，不计算业务规则。"""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from backend.domain.hotel_details import HotelDisplayDetails
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
    data_mode: Literal["fixture", "live"]
    evidence_id: UUID
    source_ref: str | None
    content_version: str | None


class ValidationFeedback(ValidationReport):
    check_counts: dict[str, int]
    truncated: bool


class PlanCard(PlanItem):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    name: str
    source_ref: str | None
    data_mode: Literal["fixture", "snapshot", "live"]


class PlanView(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    plan_id: UUID
    request_revision: int
    cards: tuple[PlanCard, ...]
    hotel: HotelCard | None
    hotel_evidence_id: UUID | None
    hotel_stays: tuple[HotelStay, ...] = Field(default=(), exclude_if=lambda value: not value)
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


class HotelPresentation(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=False)
    component: Literal["hotel_comparison"]
    cards: tuple[HotelCard, ...]
    comparison: Comparison
    total_found: int | None = None
    more_url: str | None = None
    more_url_scope: Literal["search", "destination"] | None = None

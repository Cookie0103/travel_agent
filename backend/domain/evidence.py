"""事实证据的来源、适用条件和时效；服务端按ID补全，模型不能提供事实值。"""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from backend.domain.travel_request import TravelRequest

EvidenceKind = Literal["place", "article", "hotel_offer", "route"]


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: UUID = Field(default_factory=uuid4)
    entity_id: str = Field(min_length=1, max_length=100)
    field_path: str = Field(min_length=1, max_length=100)
    value: JsonValue
    kind: EvidenceKind
    request_revision: int = Field(strict=True, ge=0)
    conditions: dict[str, JsonValue]
    provider: str | None = None
    source_ref: str | None = None
    content_version: str | None = None
    retrieved_at: AwareDatetime
    valid_until: AwareDatetime
    data_mode: Literal["fixture", "snapshot"]

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        if self.valid_until <= self.retrieved_at:
            raise ValueError("证据有效期必须晚于获取时间")
        return self

    @property
    def status(self) -> Literal["verified", "unknown"]:
        source = (self.provider, self.source_ref, self.content_version)
        return (
            "verified"
            if all(value and value.strip() for value in source) and self.value is not None
            else "unknown"
        )

    def applicable(self, request: TravelRequest, now: datetime) -> bool:
        if now.utcoffset() is None:
            raise ValueError("证据检查需要带时区的时间")
        return (
            self.retrieved_at <= now < self.valid_until
            and self.request_revision == request.revision
            and self.conditions == evidence_conditions(request, self.kind)
        )


def evidence_conditions(request: TravelRequest, kind: EvidenceKind) -> dict[str, JsonValue]:
    fields = {
        "hotel_offer": {
            "city",
            "start_date",
            "end_date",
            "adults",
            "child_ages",
            "rooms",
            "currency",
        },
        "route": {"city", "start_date", "end_date", "transport", "departure_time"},
        "place": {"city"},
        "article": {"city"},
    }[kind]
    return request.model_dump(mode="json", include=fields)

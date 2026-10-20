"""冻结0c5d7ec的报价字段；回退兼容不得依赖被测的新模型。"""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from tests.fixtures.legacy_travel_request_v1 import TravelRequest

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]


class QuoteFields(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_serialization_defaults_required=True
    )
    offer_id: UUID = Field(default_factory=uuid4)
    rate_id: str
    hotel_id: str
    hotel_name: str
    room_type: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    base_amount: Money
    tax_amount: Money | None
    fee_amount: Money | None
    breakfast: bool | None
    refundable: bool | None
    image_url: str | None = None
    review_average: float | None = None
    booking_url: str | None = None
    data_mode: Literal["fixture", "live"] = "fixture"
    included_total: Money | None = None
    total_reason: str | None = None
    quoted_at: AwareDatetime
    expires_at: AwareDatetime


class HotelOffer(QuoteFields):
    request: TravelRequest

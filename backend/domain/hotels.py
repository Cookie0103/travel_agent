"""模拟酒店报价与同口径比较的纯规则；金额和比较结论不由模型填写。"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from backend.domain.evidence import evidence_conditions
from backend.domain.travel_request import TravelRequest

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]


class HotelRate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rate_id: str
    hotel_id: str
    hotel_name: str
    room_type: str
    city: Literal["京都"] = "京都"
    currency: Literal["JPY"] = "JPY"
    max_guests_per_room: int = Field(strict=True, ge=1, le=6)
    base_per_room_night: Money
    tax_per_room_night: Money | None
    fee_per_room_night: Money | None
    weekend_surcharge: Money = Decimal(0)
    breakfast: bool
    refundable: bool
    available_from: date
    available_until: date


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
    breakfast: bool
    refundable: bool
    quoted_at: AwareDatetime
    expires_at: AwareDatetime


class HotelOffer(QuoteFields):
    request: TravelRequest

    @model_validator(mode="after")
    def valid_quote(self) -> Self:
        if self.request.hotel_requirements() or self.expires_at <= self.quoted_at:
            raise ValueError("报价必须具有完整入住条件和有效时间")
        return self

    @property
    def total(self) -> Decimal | None:
        if self.tax_amount is None or self.fee_amount is None:
            return None
        return self.base_amount + self.tax_amount + self.fee_amount

    def card(self) -> dict[str, object]:
        total = self.total
        return {
            **self.model_dump(mode="json", exclude={"request"}),
            "stay": evidence_conditions(self.request, "hotel_offer"),
            "request_revision": self.request.revision,
            "total": str(total) if total is not None else None,
            "lodging_exceeds_trip_budget": (
                total > self.request.budget
                if total is not None and self.request.budget is not None
                else None
            ),
            "data_mode": "fixture",
        }


def quote(rate: HotelRate, request: TravelRequest, now: datetime) -> HotelOffer | None:
    if request.hotel_requirements():
        raise ValueError("入住条件不完整")
    assert request.start_date and request.end_date and request.rooms and request.adults
    nights = (request.end_date - request.start_date).days
    if (
        request.city != rate.city
        or request.currency != rate.currency
        or request.start_date < rate.available_from
        or request.end_date > rate.available_until
        or request.adults + len(request.child_ages or ()) > request.rooms * rate.max_guests_per_room
    ):
        return None
    # 按房晚计费，全部入住者都计入容量；不猜测婴儿免费或儿童优惠。
    full_weeks, extra = divmod(nights, 7)
    weekends = 2 * full_weeks + sum(
        (request.start_date.weekday() + day) % 7 >= 5 for day in range(extra)
    )
    units = nights * request.rooms
    return HotelOffer(
        **rate.model_dump(
            include={
                "rate_id",
                "hotel_id",
                "hotel_name",
                "room_type",
                "currency",
                "breakfast",
                "refundable",
            }
        ),
        request=request,
        base_amount=rate.base_per_room_night * units
        + rate.weekend_surcharge * weekends * request.rooms,
        tax_amount=rate.tax_per_room_night * units if rate.tax_per_room_night is not None else None,
        fee_amount=rate.fee_per_room_night * units if rate.fee_per_room_night is not None else None,
        quoted_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def compare(offers: tuple[HotelOffer, ...], now: datetime) -> dict[str, object]:
    if now.utcoffset() is None or not offers:
        raise ValueError("比较需要报价和带时区的时间")
    first = offers[0]
    reasons: list[str] = []
    if any(
        evidence_conditions(offer.request, "hotel_offer")
        != evidence_conditions(first.request, "hotel_offer")
        for offer in offers
    ):
        reasons.append("入住日期、人数或房间数不同")
    if any(offer.currency != first.currency for offer in offers):
        reasons.append("币种不同")
    if any(offer.currency != offer.request.currency for offer in offers):
        reasons.append("报价币种与旅行条件不匹配")
    if any(offer.total is None for offer in offers):
        reasons.append("税费缺失，无法比较含税费总价")
    if any(not offer.quoted_at <= now < offer.expires_at for offer in offers):
        reasons.append("报价未生效或已过期")
    totals = [offer.total for offer in offers if offer.total is not None]
    minimum = min(totals) if not reasons else None
    return {
        "comparable": not reasons,
        "reasons": reasons,
        "lowest_offer_ids": [
            str(offer.offer_id)
            for offer in offers
            if minimum is not None and offer.total == minimum
        ],
        "scope": "仅比较列出的模拟报价含税费住宿总价；早餐、退款分别展示；不代表全程预算满足",
    }

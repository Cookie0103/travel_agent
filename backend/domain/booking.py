"""模拟预订边界契约；供应商和应用共享输入类型，状态裁决不由模型决定。"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from backend.domain.execution import ErrorCode
from backend.domain.hotels import HotelOffer, Money

type BookingStatus = Literal[
    "quoted", "held", "confirmed", "booked", "failed", "unknown", "expired"
]


class HoldInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    client_ref: UUID
    offer: HotelOffer


class SupplierHold(HoldInput):
    hold_id: UUID
    expires_at: AwareDatetime
    data_mode: Literal["fixture"] = "fixture"


class OrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    client_ref: UUID
    hold_id: UUID


class SupplierOrder(OrderInput):
    order_id: UUID
    created_at: AwareDatetime
    status: Literal["booked"] = "booked"
    data_mode: Literal["fixture"] = "fixture"


class OrderLookup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    order: SupplierOrder | None = None
    absence_final: bool = False


class HoldHotelInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    offer_id: UUID
    expected_revision: int = Field(strict=True, ge=0)


class BookingChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: BookingStatus
    at: AwareDatetime
    reason: str


class Booking(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_serialization_defaults_required=True
    )
    booking_id: UUID
    client_ref: UUID
    session_id: UUID
    evidence_id: UUID
    offer: HotelOffer
    total: Money
    source_ref: str
    content_version: str | None
    status: BookingStatus = "quoted"
    hold_id: UUID | None = None
    expires_at: AwareDatetime | None = None
    order_id: UUID | None = None
    error_code: ErrorCode | None = None
    history: tuple[BookingChange, ...] = ()
    data_mode: Literal["fixture"] = "fixture"

    def hold_expired(self, observed_at: datetime) -> bool:
        """暂留时效在服务与上下文共用；已确认/未知订单必须走对账。"""
        return self.status == "held" and (self.expires_at is None or self.expires_at <= observed_at)

    def card(self) -> dict[str, object]:
        """工具只携带预订裁决信息，完整条件与历史留在用户API。"""
        return {
            **self.model_dump(mode="json", exclude={"offer", "history"}),
            "offer": self.offer.card(),
        }

    @classmethod
    def quoted(
        cls,
        session_id: UUID,
        evidence_id: UUID,
        offer: HotelOffer,
        source_ref: str,
        content_version: str | None,
    ) -> "Booking":
        identity = uuid4()
        assert offer.total is not None
        return cls(
            booking_id=identity,
            client_ref=identity,
            session_id=session_id,
            evidence_id=evidence_id,
            offer=offer,
            total=offer.total,
            source_ref=source_ref,
            content_version=content_version,
            history=(
                BookingChange(status="quoted", at=datetime.now(UTC), reason="quote_selected"),
            ),
        )


TRANSITIONS: dict[BookingStatus, frozenset[BookingStatus]] = {
    "quoted": frozenset({"held", "failed", "expired"}),
    "held": frozenset({"confirmed", "expired"}),
    "confirmed": frozenset({"booked", "failed", "unknown"}),
    "unknown": frozenset({"booked", "failed"}),
    "booked": frozenset(),
    "failed": frozenset(),
    "expired": frozenset(),
}


def transition(booking: Booking, status: BookingStatus, reason: str, **changes: object) -> Booking:
    if status == booking.status:
        return booking
    if status not in TRANSITIONS[booking.status]:
        raise ValueError("非法预订状态转移")
    return Booking.model_validate(
        {
            **booking.model_dump(),
            **changes,
            "status": status,
            "history": (
                *booking.history,
                BookingChange(status=status, at=datetime.now(UTC), reason=reason),
            ),
        }
    )

"""模拟预订边界契约；供应商和应用共享输入类型，状态裁决不由模型决定。"""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from backend.domain.hotels import HotelOffer


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

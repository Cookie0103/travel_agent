"""供应商已有响应的展示细节；不参与价格、入住或预订协议。"""

from pydantic import BaseModel, ConfigDict, Field


class HotelMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    review_count: int | None = Field(default=None, ge=0)


class HotelDisplayDetails(HotelMetadata):
    hotel_info_url: str | None = None
    plan_list_url: str | None = None
    reservation_url: str | None = None

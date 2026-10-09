"""供应商已有响应的展示细节；不参与价格、入住或预订协议。"""

from typing import Literal

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
    price_basis: str | None = None


class StoredHotelDetails(HotelDisplayDetails):
    """随证据保存的展示细节；比卡片多出本次搜索的整体信息，由present提到展示顶层，不进卡片。"""

    search_total_found: int | None = Field(default=None, ge=0)
    more_url: str | None = None
    more_url_scope: Literal["search", "destination"] | None = None

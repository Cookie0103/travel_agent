"""供应商已有响应的展示细节；不参与价格、入住或预订协议。"""

from pydantic import BaseModel, ConfigDict


class HotelDisplayDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    hotel_info_url: str | None = None
    plan_list_url: str | None = None
    reservation_url: str | None = None

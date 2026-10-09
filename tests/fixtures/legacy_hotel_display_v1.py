"""冻结T4.2/T4.3三URL展示reader（2be5f8c），验证回退兼容。"""

from pydantic import BaseModel, ConfigDict


class HotelDisplayDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    hotel_info_url: str | None = None
    plan_list_url: str | None = None
    reservation_url: str | None = None

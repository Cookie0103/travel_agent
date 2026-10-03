"""地点与攻略的公开快照契约；导入验证后供查询和行程校验共用。"""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["osm", "wikivoyage"]
    source_ref: str = Field(min_length=1)
    content_version: str = Field(min_length=1)
    retrieved_at: AwareDatetime
    license: str = Field(min_length=1)
    license_url: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    data_mode: Literal["snapshot"] = "snapshot"


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    place_id: str
    osm_id: str
    city: Literal["京都"] = "京都"
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    coordinate_kind: Literal["node", "bounding_box_center"]
    category: str
    indoor: bool | None = None
    opening_hours: str | None = None
    source: Source
    field_sources: dict[str, str]


class Article(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    article_id: str
    city: Literal["京都"] = "京都"
    title: str
    text: str = Field(min_length=1, max_length=3000)
    category: str = "guide"
    mentioned_places: tuple[str, ...] = ()
    source: Source

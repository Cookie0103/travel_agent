"""地点与攻略的公开快照契约；导入验证后供查询和行程校验共用。"""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["osm", "wikivoyage", "google_places"]
    source_ref: str = Field(min_length=1)
    content_version: str = Field(min_length=1)
    retrieved_at: AwareDatetime
    license: str = Field(min_length=1)
    license_url: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    data_mode: Literal["snapshot", "live"] = "snapshot"


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    place_id: str
    osm_id: str | None = None
    city: str = "京都"
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = Field(
        default=(), description="有来源的别名和历史检索名；不替代当前名称，不表示街区边界"
    )
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
    city: str = "京都"
    title: str
    text: str = Field(min_length=1, max_length=3000)
    category: str = "guide"
    mentioned_places: tuple[str, ...] = ()
    source: Source


SIGHTSEEING_CATEGORIES = {
    "museum",
    "castle",
    "attraction",
    "tourist_attraction",
    "viewpoint",
    "heritage",
    "memorial",
    "monument",
    "ruins",
    "archaeological_site",
    "boundary_stone",
    "wayside_shrine",
    "place_of_worship",
    "temple",
    "shrine",
    "church",
    "mosque",
    "synagogue",
    "hindu_temple",
    "buddhist_temple",
    "art_gallery",
    "gallery",
    "artwork",
    "zoo",
    "aquarium",
    "theme_park",
    "amusement_park",
    "park",
    "garden",
    "national_park",
    "historical_landmark",
    "cultural_landmark",
    "historical_place",
    "observation_deck",
    "scenic_spot",
    "natural_feature",
    "market",
    "shopping_mall",
}

# 来源明确标出的生活/中转用途优先于宽泛的 tourist_attraction 标签。
NON_SIGHTSEEING_CATEGORIES = {
    "hotel",
    "lodging",
    "hostel",
    "motel",
    "resort_hotel",
    "bed_and_breakfast",
    "guest_house",
    "apartment",
    "restaurant",
    "cafe",
    "coffee_shop",
    "bar",
    "meal_takeaway",
    "meal_delivery",
    "bakery",
    "train_station",
    "transit_station",
    "subway_station",
    "bus_station",
    "bus_stop",
    "airport",
    "ferry_terminal",
    "parking",
    "taxi_stand",
}


def place_category(categories: list[str]) -> str:
    """保留来源的具体用途；不因 Google 多类型顺序丢掉已知景点类别。"""
    normalized = [category.strip().casefold() for category in categories]
    return (
        next((c for c in normalized if c in NON_SIGHTSEEING_CATEGORIES), "")
        or next((c for c in normalized if c in SIGHTSEEING_CATEGORIES), "")
        or (normalized[0] if normalized else "unknown")
    )


class ContentSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    city: str = Field(min_length=1, max_length=40, description="城市是硬过滤条件，例如京都")
    query: str = Field(
        default="", max_length=100, description="简短关键词，支持原名、中文别名和标签"
    )
    category: str | None = Field(default=None, max_length=40)
    limit: int = Field(default=5, ge=1, le=8)


class PlaceSearchInput(ContentSearchInput):
    indoor: bool | None = Field(default=None, description="室内景点为 true")


def search(rows: list[dict[str, object]], arguments: ContentSearchInput) -> list[dict[str, object]]:
    city = "京都" if arguments.city.casefold() in {"kyoto", "京都", "京都市"} else arguments.city
    query = arguments.query.casefold()
    found: list[dict[str, object]] = []
    for row in rows:
        if str(row.get("city", "")).casefold() != city.casefold():
            continue
        if arguments.category and row.get("category") != arguments.category:
            continue
        if isinstance(arguments, PlaceSearchInput):
            if arguments.indoor is not None and row.get("indoor") != arguments.indoor:
                continue
        searchable = " ".join(
            str(row.get(k, "")) for k in ("name", "aliases", "title", "text", "tags")
        )
        if query and query not in searchable.casefold():
            continue
        found.append(row)
        if len(found) == arguments.limit:
            break
    return found

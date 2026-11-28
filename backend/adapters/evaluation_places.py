"""六城隔离评测的地点目录。名称与可用时段等测试事实独立于实时数据。"""

from dataclasses import dataclass
from unicodedata import normalize

from backend.domain.travel_request import CITY_ALIASES


@dataclass(frozen=True)
class Category:
    code: str
    names: tuple[str, ...]
    indoor: bool


CATEGORIES = (
    Category("museum", ("博物馆", "博物館", "museum"), True),
    Category("art_gallery", ("美术馆", "美術館", "画廊", "art gallery"), True),
    Category("park", ("公园", "公園", "park"), False),
    Category("garden", ("庭园", "庭園", "花园", "庭院", "garden"), False),
    Category("aquarium", ("水族馆", "水族館", "aquarium"), True),
    Category("zoo", ("动物园", "動物園", "zoo"), False),
    Category("viewpoint", ("观景点", "展望台", "观景台", "viewpoint"), False),
    Category("shopping_mall", ("购物中心", "商场", "商業施設", "shopping mall"), True),
    Category("shrine", ("神社", "shrine"), False),
    Category("temple", ("寺院", "寺庙", "寺廟", "temple"), False),
    Category("national_park", ("国家公园", "国立公園", "national park"), False),
    Category("restaurant", ("餐厅", "餐廳", "餐馆", "レストラン", "restaurant"), True),
    Category("cafe", ("咖啡馆", "咖啡店", "カフェ", "cafe", "café"), True),
)
CATEGORIES_BY_CODE = {
    item.code: item for item in (*CATEGORIES, Category("castle", ("城堡", "castle"), False))
}


@dataclass(frozen=True)
class NamedPlace:
    name: str
    category: str
    aliases: tuple[str, ...] = ()
    open_minute: int = 9 * 60
    close_minute: int = 18 * 60 + 30
    closed_day: int | None = None
    reservation_required: bool = False


NAMED_PLACES = {
    "京都": (
        NamedPlace(
            "桂離宮",
            "garden",
            ("桂离宫", "Katsura Imperial Villa"),
            close_minute=16 * 60,
            closed_day=1,
            reservation_required=True,
        ),
        NamedPlace("清水寺", "temple", ("Kiyomizu-dera",)),
    ),
    "東京": (
        NamedPlace(
            "三鷹の森ジブリ美術館",
            "museum",
            ("三鹰之森吉卜力美术馆", "吉卜力", "ジブリ", "Ghibli Museum"),
            open_minute=10 * 60,
            close_minute=18 * 60,
            closed_day=2,
            reservation_required=True,
        ),
        NamedPlace("上野動物園", "zoo", ("上野动物园", "Ueno Zoo"), closed_day=1),
    ),
    "大阪": (
        NamedPlace("海遊館", "aquarium", ("海游馆", "Kaiyukan")),
        NamedPlace("大阪城", "castle", ("Osaka Castle",)),
    ),
    "奈良": (
        NamedPlace("東大寺", "temple", ("东大寺", "Tōdai-ji", "Todai-ji")),
        NamedPlace("奈良公園", "park", ("奈良公园", "Nara Park")),
    ),
    "札幌": (
        NamedPlace("大通公園", "park", ("大通公园", "Odori Park")),
        NamedPlace("白い恋人パーク", "garden", ("白色恋人公园", "Shiroi Koibito Park")),
    ),
    "福岡": (
        NamedPlace("太宰府天満宮", "shrine", ("太宰府天满宫", "Dazaifu Tenmangu")),
        NamedPlace("大濠公園", "park", ("大濠公园", "Ohori Park")),
    ),
}


@dataclass(frozen=True)
class FixturePlace:
    identity: str
    name: str
    category: Category
    latitude: float
    longitude: float
    open_minute: int
    close_minute: int
    closed_day: int | None
    aliases: tuple[str, ...] = ()
    reservation_required: bool = False

    def response(self) -> dict[str, object]:
        return {
            "id": self.identity,
            "displayName": {"text": self.name},
            "location": {"latitude": self.latitude, "longitude": self.longitude},
            "types": [self.category.code],
            "evaluationIndoor": self.category.indoor,
            "evaluationAliases": self.aliases,
            **({"evaluationReservationRequired": True} if self.reservation_required else {}),
            "regularOpeningHours": {
                "periods": [
                    {
                        "open": {
                            "day": day,
                            "hour": self.open_minute // 60,
                            "minute": self.open_minute % 60,
                        },
                        "close": {
                            "day": day,
                            "hour": self.close_minute // 60,
                            "minute": self.close_minute % 60,
                        },
                    }
                    for day in range(7)
                    if day != self.closed_day
                ],
            },
        }


def _location(latitude: float, longitude: float, index: int) -> tuple[float, float]:
    # 两条轴用不同的周期，保留近距离邻居和跨街区的路线样本。
    north = ((index * 3) % 11 - 5) * 0.0044 + (index // 11) * 0.0002
    east = ((index * 5) % 13 - 6) * 0.0039
    return round(latitude + north, 6), round(longitude + east, 6)


def city_places(city: str, latitude: float, longitude: float) -> tuple[FixturePlace, ...]:
    result = []
    for index, named in enumerate(NAMED_PLACES.get(city, ())):
        point = _location(latitude, longitude, index)
        result.append(
            FixturePlace(
                f"phase2-{city}-3"
                if named.reservation_required
                else f"phase2-{city}-named-{index + 1}",
                named.name,
                CATEGORIES_BY_CODE[named.category],
                *point,
                named.open_minute,
                named.close_minute,
                named.closed_day,
                named.aliases,
                named.reservation_required,
            )
        )
    for variant in (0, 1):
        for index, category in enumerate(CATEGORIES):
            point = _location(latitude, longitude, len(result))
            result.append(
                FixturePlace(
                    f"phase2-{city}-{category.code}-{variant + 1}",
                    f"合成{city}{category.names[0]}{variant + 1}",
                    category,
                    *point,
                    480 if variant == 0 else 540,
                    1140 if variant == 0 else 960,
                    None if variant == 0 else 1 + index % 2,
                    reservation_required=variant == 1
                    and category.code in {"museum", "art_gallery", "aquarium"},
                )
            )
    return tuple(result)


def _key(value: str) -> str:
    return "".join(normalize("NFKC", value).casefold().split())


def search_places(
    catalog: tuple[FixturePlace, ...], query: str, city: str
) -> tuple[FixturePlace, ...]:
    query_key = _key(query)
    named = tuple(
        place
        for place in catalog
        if any(_key(name) in query_key for name in (place.name, *place.aliases))
    )
    if named:
        return named
    topics = {
        kind.code
        for kind in CATEGORIES_BY_CODE.values()
        if any(_key(alias) in query_key for alias in (kind.code, *kind.names))
    }
    indoor = any(term in query_key for term in ("室内", "室內", "屋内", "indoor"))
    outdoor = any(term in query_key for term in ("室外", "户外", "戶外", "outdoor"))
    if topics or indoor or outdoor:
        return tuple(
            place
            for place in catalog
            if (not topics or place.category.code in topics)
            and (not indoor or place.category.indoor)
            and (not outdoor or not place.category.indoor)
        )
    aliases = (_key(alias) for alias, canonical in CITY_ALIASES.items() if canonical == city)
    if query_key in {_key(city), *aliases} or any(
        term in query_key for term in ("景点", "景點", "観光", "观光", "sightseeing", "attractions")
    ):
        return tuple(
            place for place in catalog if place.category.code not in {"restaurant", "cafe"}
        )
    return ()

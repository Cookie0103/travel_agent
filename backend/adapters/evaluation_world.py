"""已隔离评测运行器传入的供应商夹具，只含可展示事实。"""

import json
from datetime import date
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.domain.travel_request import CITY_ALIASES, city_key

type Demand = Literal["weekday", "weekend", "event"]

PLACE_TYPES = (
    "museum",
    "park",
    "art_gallery",
    "garden",
    "aquarium",
    "viewpoint",
    "shopping_mall",
    "shrine",
    "museum",
    "zoo",
    "art_gallery",
    "national_park",
)


class EvaluationHotel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    number: int = Field(gt=0)
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    rating: float = Field(ge=0, le=5)
    reviews: int = Field(ge=0)
    breakfast: bool
    partner: bool = False
    prices_jpy: dict[Demand, tuple[int, int]]


class EvaluationCity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    city: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    hotels: tuple[EvaluationHotel, ...] = Field(min_length=12, max_length=20)


class EvaluationWorld(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    today: date
    cities: tuple[EvaluationCity, ...] = Field(min_length=6, max_length=6)


def _city(text: str, world: EvaluationWorld) -> EvaluationCity | None:
    normalized = city_key(text)
    for city in world.cities:
        aliases = (name for name, canonical in CITY_ALIASES.items() if canonical == city.city)
        if normalized == city.city or any(alias in normalized for alias in (*aliases, city.city)):
            return city
    return None


def places(city: EvaluationCity) -> list[dict[str, object]]:
    named = {"東京": "三鷹の森ジブリ美術館", "京都": "桂離宮"}.get(city.city)
    return [
        {
            "id": f"phase2-{city.city}-{index + 1}",
            "displayName": {
                "text": named
                if named and index == 2
                else f"合成{city.city}{place_type}景点{index + 1}"
            },
            "location": {
                "latitude": city.latitude + index * 0.00062,
                "longitude": city.longitude - index * 0.00048,
            },
            "types": [place_type],
            "regularOpeningHours": {"periods": [{"open": {"day": 0}}]},
        }
        for index, place_type in enumerate(PLACE_TYPES)
    ]


def serve(request: httpx.Request, world: EvaluationWorld) -> httpx.Response | None:
    host, path = request.url.host, request.url.path
    if host == "maps.googleapis.com" and "geocode" in path:
        city = _city(request.url.params.get("address", ""), world)
        if city is None:
            return httpx.Response(200, json={"status": "ZERO_RESULTS"})
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {
                        "place_id": "phase2-city-" + city.city,
                        "address_components": [
                            {"long_name": "日本", "short_name": "JP", "types": ["country"]},
                            {
                                "long_name": city.city,
                                "short_name": city.city,
                                "types": ["locality"],
                            },
                        ],
                        "geometry": {"location": {"lat": city.latitude, "lng": city.longitude}},
                    }
                ],
            },
        )
    if host == "places.googleapis.com":
        if request.method == "GET":
            identity = path.rsplit("/", 1)[-1]
            place = next(
                (
                    place
                    for city in world.cities
                    for place in places(city)
                    if place["id"] == identity
                ),
                None,
            )
            return httpx.Response(200, json=place) if place else httpx.Response(404)
        payload = json.loads(request.content)
        query = str(payload.get("textQuery", ""))
        city = _city(query, world)
        found = places(city) if city else []
        if any(name in query for name in ("吉卜力", "ジブリ", "桂离宫", "桂離宮")) and found:
            found.insert(0, found.pop(2))
        limit = int(payload.get("maxResultCount", 8))
        return httpx.Response(200, json={"places": found[:limit]})
    if host in {"openapi.rakuten.co.jp", "app.rakuten.co.jp"}:
        params = request.url.params
        wanted = set(params["hotelNo"].split(",")) if "hotelNo" in params else set()
        by_coordinates = not wanted and "latitude" in params and "longitude" in params
        found_hotels = []
        if wanted:
            found_hotels = [
                hotel
                for city in world.cities
                for hotel in city.hotels
                if str(hotel.number) in wanted
            ]
        elif by_coordinates:
            latitude, longitude = float(params["latitude"]), float(params["longitude"])
            city = min(
                world.cities,
                key=lambda item: (
                    (item.latitude - latitude) ** 2 + (item.longitude - longitude) ** 2
                ),
            )
            found_hotels = list(city.hotels)
        day = date.fromisoformat(params["checkinDate"])
        demand: Demand = (
            "event" if day.day in {1, 3, 23, 31} else "weekend" if day.weekday() >= 4 else "weekday"
        )
        group = min(2, int(params.get("adultNum", "1"))) - 1
        hotels = [
            [
                {
                    "hotelBasicInfo": {
                        "hotelNo": h.number,
                        "hotelName": h.name,
                        "latitude": h.latitude,
                        "longitude": h.longitude,
                        "reviewAverage": h.rating,
                        "reviewCount": h.reviews,
                        "evaluationPartner": h.partner,
                    }
                },
                {
                    "hotelDetailInfo": {
                        "checkinTime": "15:00",
                        "lastCheckinTime": "23:00",
                        "checkoutTime": "10:00",
                    }
                },
                {
                    "roomInfo": [
                        {
                            "roomBasicInfo": {
                                "roomClass": "twin",
                                "roomName": "禁煙ツイン個室",
                                "planId": h.number,
                                "withBreakfastFlag": int(h.breakfast),
                            }
                        },
                        {
                            "dailyCharge": {
                                "stayDate": day.isoformat(),
                                "rakutenCharge": h.prices_jpy[demand][group],
                                "chargeFlag": 1,
                                "evaluationChildCharge": 2400,  # 合成世界每儿童每晚日元
                            }
                        },
                    ]
                },
            ]
            for h in found_hotels
        ]
        return httpx.Response(
            200, json={"pagingInfo": {"recordCount": len(hotels)}, "hotels": hotels}
        )
    if host == "routes.googleapis.com":
        return httpx.Response(200, json={"routes": [{"duration": "600s"}]})
    return None

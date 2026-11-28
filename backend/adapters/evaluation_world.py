"""已隔离评测运行器传入的供应商夹具，只含可展示事实。"""

import json
from datetime import date
from math import cos, hypot, radians
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.adapters.evaluation_places import city_places, search_places
from backend.domain.external_data import Coordinates
from backend.domain.travel_request import CITY_ALIASES, city_key

type Demand = Literal["weekday", "weekend", "event"]

type EvaluationWeather = Literal["rain", "sunny"]


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
    prices_jpy: dict[Demand, tuple[int | None, int | None]]
    breakfast_by_demand: dict[Demand, tuple[bool | None, bool | None]] | None = None
    room_type: str = "禁煙ツイン個室"
    max_guests: int | None = Field(default=None, ge=1, le=4)


class EvaluationCity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    city: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    hotels: tuple[EvaluationHotel, ...] = Field(min_length=12, max_length=20)


class EvaluationWorld(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: Literal["synthetic", "rakuten"] = "synthetic"
    today: date
    cities: tuple[EvaluationCity, ...] = Field(min_length=6, max_length=6)
    weather_by_date: dict[date, EvaluationWeather] = Field(default_factory=dict)
    synthetic_calendar: bool = False


def _city(text: str, world: EvaluationWorld) -> EvaluationCity | None:
    normalized = city_key(text)
    for city in world.cities:
        aliases = (name for name, canonical in CITY_ALIASES.items() if canonical == city.city)
        if normalized == city.city or any(alias in normalized for alias in (*aliases, city.city)):
            return city
    return None


def places(city: EvaluationCity) -> list[dict[str, object]]:
    return [place.response() for place in city_places(city.city, city.latitude, city.longitude)]


def _route_seconds(request: httpx.Request) -> int:
    payload = json.loads(request.content)
    if payload.get("travelMode") != "WALK":
        return 600
    start = Coordinates.model_validate(payload["origin"]["location"]["latLng"])
    end = Coordinates.model_validate(payload["destination"]["location"]["latLng"])
    # 城市尺度的平面近似，按 80 米/分钟生成离线时长。
    latitude = radians((start.latitude + end.latitude) / 2)
    meters = 111_000 * hypot(
        end.latitude - start.latitude, (end.longitude - start.longitude) * cos(latitude)
    )
    return max(60, round(meters * 60 / 80))


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
        if city is None:
            return httpx.Response(200, json={"places": []})
        catalog = city_places(city.city, city.latitude, city.longitude)
        limit = int(payload.get("pageSize", payload.get("maxResultCount", 8)))
        found = search_places(catalog, query, city.city)[:limit]
        return httpx.Response(200, json={"places": [place.response() for place in found]})
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
        adults = int(params.get("adultNum", "1"))
        if world.source == "rakuten" and adults not in (1, 2):
            return httpx.Response(200, json={"pagingInfo": {"recordCount": 0}, "hotels": []})
        group = min(2, adults) - 1
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
                                "roomClass": "family" if h.max_guests == 4 else "twin",
                                "roomName": h.room_type,
                                "planId": h.number,
                                **(
                                    {"evaluationMaxGuests": h.max_guests}
                                    if world.source == "synthetic" and h.max_guests is not None
                                    else {}
                                ),
                                "withBreakfastFlag": int(
                                    bool(h.breakfast_by_demand[demand][group])
                                    if h.breakfast_by_demand is not None
                                    else h.breakfast
                                ),
                            }
                        },
                        {
                            "dailyCharge": {
                                "stayDate": day.isoformat(),
                                "rakutenCharge": h.prices_jpy[demand][group],
                                "chargeFlag": 1,
                                **(
                                    {"evaluationFixedPerRoom": True}
                                    if world.source == "synthetic"
                                    and h.max_guests is not None
                                    and h.prices_jpy[demand][0] == h.prices_jpy[demand][1]
                                    else {}
                                ),
                                **(
                                    {"evaluationChildCharge": 2400}
                                    if world.source == "synthetic"
                                    else {}
                                ),
                            }
                        },
                    ]
                },
            ]
            for h in found_hotels
            if h.prices_jpy[demand][group] is not None
        ]
        return httpx.Response(
            200, json={"pagingInfo": {"recordCount": len(hotels)}, "hotels": hotels}
        )
    if host == "routes.googleapis.com":
        return httpx.Response(200, json={"routes": [{"duration": f"{_route_seconds(request)}s"}]})
    return None

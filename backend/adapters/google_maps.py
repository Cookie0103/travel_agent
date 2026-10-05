"""Google 地理编码、景点与路线；详情仅在本轮处理，持久缓存只存ID/坐标。"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import ceil

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.adapters.external_api import ApiUsage, parse_response, request_json
from backend.domain.catalog import Place, Source
from backend.domain.external_data import Coordinates, ExternalDataError, GeoPoint
from backend.domain.itinerary import RouteEstimate
from backend.domain.travel_request import Transport


class _LatLng(BaseModel):
    lat: float
    lng: float


class _Geometry(BaseModel):
    location: _LatLng
    viewport: dict[str, _LatLng] = Field(default_factory=dict)


class _Component(BaseModel):
    long_name: str
    short_name: str
    types: list[str]


class _GeocodeResult(BaseModel):
    place_id: str
    address_components: list[_Component]
    geometry: _Geometry


class _GeocodeResponse(BaseModel):
    status: str
    results: list[_GeocodeResult] = Field(default_factory=list)


class _Time(BaseModel):
    day: int = Field(ge=0, le=6)
    hour: int = Field(default=0, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)


class _Period(BaseModel):
    open: _Time
    close: _Time | None = None


class _Hours(BaseModel):
    periods: list[_Period] = Field(default_factory=list)


class _DisplayName(BaseModel):
    text: str


class _GooglePlace(BaseModel):
    id: str
    displayName: _DisplayName
    location: Coordinates
    types: list[str] = Field(default_factory=list)
    regularOpeningHours: _Hours | None = None
    googleMapsUri: str | None = None


class _Places(BaseModel):
    places: list[_GooglePlace] = Field(default_factory=list)


def broad_region(city: str) -> bool:
    # 以用户明确的省级表达判断；札幌等面积较大的城市仍可搜索住宿。
    value = city.strip().casefold()
    return value in {
        "北海道",
        "hokkaido",
        "沖縄",
        "冲绳",
        "沖縄県",
        "okinawa",
        "东京都",
        "東京都",
    } or value.endswith(("県", "县", "府"))


def opening_hours(hours: _Hours | None) -> str | None:
    if not hours or not hours.periods:
        return None
    parts: dict[str, list[str]] = {}
    for period in hours.periods:
        start, end = period.open, period.close
        if end is None:
            return "24/7" if len(hours.periods) == 1 and start.hour == start.minute == 0 else None
        if (end.day - start.day) % 7 not in (0, 1):
            return None
        if end.day != start.day and start.hour == start.minute == end.hour == end.minute == 0:
            parts.setdefault(("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")[start.day], []).append(
                "00:00-24:00"
            )
            continue
        if end.day != start.day and (end.hour, end.minute) >= (start.hour, start.minute):
            return None
        parts.setdefault(("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")[start.day], []).append(
            f"{start.hour:02}:{start.minute:02}-{end.hour:02}:{end.minute:02}"
        )
    return "; ".join(f"{day} {','.join(intervals)}" for day, intervals in parts.items())


def place_from_response(value: _GooglePlace, city: str) -> Place:
    now = datetime.now(UTC)
    return Place(
        place_id="gplace:" + value.id,
        city=city,
        name=value.displayName.text,
        latitude=value.location.latitude,
        longitude=value.location.longitude,
        coordinate_kind="node",
        category=value.types[0] if value.types else "attraction",
        opening_hours=opening_hours(value.regularOpeningHours),
        field_sources={},
        source=Source(
            provider="google_places",
            source_ref=value.googleMapsUri
            or f"https://www.google.com/maps/search/?api=1&query_place_id={value.id}&query=place",
            content_version=now.isoformat(),
            retrieved_at=now,
            license="Google Maps Platform Terms",
            license_url="https://cloud.google.com/maps-platform/terms",
            attribution="Google Maps",
            data_mode="live",
        ),
    )


class GoogleMaps:
    def __init__(self, api_key: str, http: httpx.AsyncClient, usage: ApiUsage) -> None:
        self.api_key, self.http, self.usage = api_key, http, usage
        self.points: dict[str, GeoPoint] = {}
        self.places: dict[str, Place] = {}

    async def geocode(self, city: str) -> GeoPoint:
        if city in self.points:
            return self.points[city]
        threshold = datetime.now(UTC) - timedelta(days=30)
        async with self.usage.database.sessions.begin() as db:
            await db.execute(
                text("DELETE FROM google_coordinates WHERE fetched_at <= :expiry"),
                {"expiry": threshold},
            )
            cached = (
                (
                    await db.execute(
                        text(
                            "SELECT latitude, longitude FROM google_coordinates WHERE query=:query"
                        ),
                        {"query": "city:" + city.casefold()},
                    )
                )
                .mappings()
                .first()
            )
        if cached:
            point = GeoPoint.model_validate({**cached, "name": city, "broad": broad_region(city)})
        else:
            payload = await request_json(
                self.http,
                self.usage,
                "geocode",
                "GET",
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={
                    "address": city,
                    "components": "country:JP",
                    "language": "ja",
                    "key": self.api_key,
                },
            )
            result = parse_response(_GeocodeResponse, payload)
            if result.status == "ZERO_RESULTS":
                raise ExternalDataError(
                    "未找到日本国内目的地；目前只支持日本国内，请提供具体城市", validation=True
                )
            if result.status != "OK" or not result.results:
                raise ExternalDataError(f"地理编码不可用（{result.status}），请检查API配置")
            entry = result.results[0]
            if not any(
                "country" in item.types and item.short_name == "JP"
                for item in entry.address_components
            ):
                raise ExternalDataError("目前只支持日本国内目的地", validation=True)
            name = next(
                (item.long_name for item in entry.address_components if "locality" in item.types),
                city,
            )
            viewport = {
                "low": entry.geometry.viewport.get("southwest"),
                "high": entry.geometry.viewport.get("northeast"),
            }
            bounds = {
                key: Coordinates(latitude=value.lat, longitude=value.lng)
                for key, value in viewport.items()
                if value
            }
            point = GeoPoint(
                latitude=entry.geometry.location.lat,
                longitude=entry.geometry.location.lng,
                name=name,
                viewport=bounds or None,
                broad=broad_region(city),
            )
            await self._save_coordinates("city:" + city.casefold(), entry.place_id, point)
        self.points[city] = point
        return point

    async def _save_coordinates(self, query: str, place_id: str, point: Coordinates) -> None:
        async with self.usage.database.sessions.begin() as db:
            await db.execute(
                text(
                    "INSERT INTO google_coordinates(query,place_id,latitude,longitude,fetched_at) "
                    "VALUES (:query,:id,:lat,:lng,:now) ON CONFLICT(query) DO UPDATE SET "
                    "place_id=:id,latitude=:lat,longitude=:lng,fetched_at=:now"
                ),
                {
                    "query": query,
                    "id": place_id,
                    "lat": point.latitude,
                    "lng": point.longitude,
                    "now": datetime.now(UTC),
                },
            )

    def _headers(self, fields: str) -> dict[str, str]:
        return {"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": fields}

    async def search_places(self, city: str, query: str, limit: int) -> tuple[Place, ...]:
        geo = await self.geocode(city)
        body: dict[str, object] = {
            "textQuery": f"{query or '観光スポット'} {geo.name}",
            "languageCode": "zh-CN",
            "regionCode": "JP",
            "pageSize": min(limit, 8),
        }
        if geo.broad and geo.viewport:
            body["locationRestriction"] = {
                "rectangle": {key: value.model_dump() for key, value in geo.viewport.items()}
            }
        else:
            body["locationBias"] = {
                "circle": {
                    "center": {"latitude": geo.latitude, "longitude": geo.longitude},
                    "radius": 15000,
                }
            }
        payload = await request_json(
            self.http,
            self.usage,
            "places",
            "POST",
            "https://places.googleapis.com/v1/places:searchText",
            headers=self._headers(
                "places.id,places.displayName,places.location,places.types,places.regularOpeningHours,places.googleMapsUri"
            ),
            body=body,
        )
        result = tuple(
            place_from_response(item, city) for item in parse_response(_Places, payload).places
        )
        for item in result:
            self.places[item.place_id] = item
            await self._save_coordinates(
                item.place_id,
                item.place_id.removeprefix("gplace:"),
                Coordinates(latitude=item.latitude, longitude=item.longitude),
            )
        return result

    async def details(self, place_id: str, city: str) -> Place:
        if place_id in self.places:
            return self.places[place_id].model_copy(update={"city": city})
        payload = await request_json(
            self.http,
            self.usage,
            "places",
            "GET",
            "https://places.googleapis.com/v1/places/" + place_id.removeprefix("gplace:"),
            headers=self._headers(
                "id,displayName,location,types,regularOpeningHours,googleMapsUri"
            ),
        )
        return place_from_response(parse_response(_GooglePlace, payload), city)

    async def route(
        self, origin: Place, dest: Place, transport: Transport, departure: datetime, people: int
    ) -> RouteEstimate:
        body: dict[str, object] = {
            "origin": {
                "location": {"latLng": {"latitude": origin.latitude, "longitude": origin.longitude}}
            },
            "destination": {
                "location": {"latLng": {"latitude": dest.latitude, "longitude": dest.longitude}}
            },
            "travelMode": {"walk": "WALK", "transit": "TRANSIT", "taxi": "DRIVE"}[transport],
        }
        if transport == "transit":
            body["departureTime"] = departure.astimezone(UTC).isoformat().replace("+00:00", "Z")
        try:
            payload = await request_json(
                self.http,
                self.usage,
                "routes",
                "POST",
                "https://routes.googleapis.com/directions/v2:computeRoutes",
                headers=self._headers("routes.duration,routes.travelAdvisory.transitFare"),
                body=body,
            )
            routes = payload.get("routes")
            route = routes[0] if isinstance(routes, list) and routes else None
            if not isinstance(route, dict) or not isinstance(route.get("duration"), str):
                raise ValueError
            duration = route["duration"]
            assert isinstance(duration, str)
            minutes = ceil(Decimal(duration.removesuffix("s")) / 60)
            fare = None
            advisory = route.get("travelAdvisory")
            money = advisory.get("transitFare") if isinstance(advisory, dict) else None
            if isinstance(money, dict) and money.get("currencyCode") == "JPY":
                fare = (
                    Decimal(str(money.get("units", 0)))
                    + Decimal(str(money.get("nanos", 0))) / 1_000_000_000
                ) * people
            return RouteEstimate(
                from_place_id=origin.place_id,
                to_place_id=dest.place_id,
                transport=transport,
                departure=departure,
                minutes=minutes,
                fare=fare,
                confidence="estimate",
            )
        except (ExternalDataError, ValueError, ArithmeticError):
            return RouteEstimate(
                from_place_id=origin.place_id,
                to_place_id=dest.place_id,
                transport=transport,
                departure=departure,
                confidence="unknown",
            )

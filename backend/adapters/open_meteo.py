"""Open-Meteo 的16天预报；超出范围保持未知，不以历史天气替代。"""

from datetime import UTC, date, datetime, timedelta

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.external_api import ApiUsage, parse_response, request_json
from backend.adapters.live_data import LiveData
from backend.domain.external_data import ExternalDataError, GeoPoint, ProviderDataMode
from backend.domain.travel_request import (
    TravelRequest,
    city_key,
    segment_request,
    tokyo_today,
    trip_segments,
)
from backend.persistence.models import WeatherForecastRow


class Daily(BaseModel):
    time: list[str]
    weather_code: list[int | None]
    temperature_2m_max: list[float | None]
    temperature_2m_min: list[float | None]
    precipitation_probability_max: list[int | None]


class Forecast(BaseModel):
    daily: Daily


def description(code: int | None) -> str:
    if code == 0:
        return "晴"
    if code in {1, 2, 3}:
        return "多云"
    if code in {45, 48}:
        return "雾"
    if code in {51, 53, 55, 56, 57}:
        return "毛毛雨"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "雨"
    if code in {71, 73, 75, 77, 85, 86}:
        return "雪"
    if code in {95, 96, 99}:
        return "雷雨"
    return "未知"


async def forecast(
    http: httpx.AsyncClient,
    usage: ApiUsage,
    point: GeoPoint,
    request: TravelRequest,
    *,
    data_mode: ProviderDataMode = "live",
    today: date | None = None,
) -> dict[str, object]:
    today = today or tokyo_today()
    if not request.start_date or not request.end_date:
        return {"status": "unknown", "reason": "旅行日期尚未确定"}
    start, end = max(request.start_date, today), min(request.end_date, today + timedelta(days=15))
    if end < start:
        return {"status": "unknown", "reason": "旅行日期超出16天预报范围，临近出行再查询"}
    partial = start != request.start_date or end != request.end_date

    def cover(payload: dict[str, object]) -> dict[str, object]:
        return (
            {**payload, "status": "partial", "reason": "未列日期超出16天预报范围"}
            if partial
            else payload
        )

    now = datetime.now(UTC)
    city = city_key(request.city or point.name)
    async with usage.database.sessions() as db:
        cached = await db.scalar(
            select(WeatherForecastRow).where(
                WeatherForecastRow.city == city,
                WeatherForecastRow.start_date == start,
                WeatherForecastRow.end_date == end,
                WeatherForecastRow.fetched_at > now - timedelta(hours=3),
            )
        )
        if cached:
            return cover(dict(cached.payload))
    data = parse_response(
        Forecast,
        await request_json(
            http,
            usage,
            "weather",
            "GET",
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": point.latitude,
                "longitude": point.longitude,
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max",
                "timezone": "Asia/Tokyo",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        ),
    ).daily
    columns = (
        data.weather_code,
        data.temperature_2m_max,
        data.temperature_2m_min,
        data.precipitation_probability_max,
    )
    expected_days = [
        (start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)
    ]
    if data.time != expected_days:
        raise ExternalDataError("天气响应为空或日期范围不匹配")
    if any(len(column) != len(data.time) for column in columns):
        raise ExternalDataError("天气响应字段长度不匹配")
    result: dict[str, object] = {
        "status": "verified",
        "days": [
            {
                "date": day,
                "description": description(code),
                "high": high,
                "low": low,
                "rain_probability": rain,
            }
            for day, code, high, low, rain in zip(
                data.time,
                data.weather_code,
                data.temperature_2m_max,
                data.temperature_2m_min,
                data.precipitation_probability_max,
                strict=True,
            )
        ],
        "source_ref": "synthetic:weather"
        if data_mode == "synthetic"
        else "https://open-meteo.com/",
        "attribution": "合成评测数据" if data_mode == "synthetic" else "Open-Meteo.com (CC BY 4.0)",
        "retrieved_at": now.isoformat(),
    }
    async with usage.database.sessions.begin() as db:
        statement = insert(WeatherForecastRow).values(
            city=city,
            start_date=start,
            end_date=end,
            payload=result,
            fetched_at=now,
        )
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=["city", "start_date", "end_date"],
                set_={"payload": result, "fetched_at": now},
            )
        )
    return cover(result)


async def city_forecast(live: LiveData, request: TravelRequest) -> dict[str, object]:
    segments = trip_segments(request)
    if not segments:
        return {"status": "unknown", "reason": "旅行城市或日期尚未确定"}
    if live.google is None:
        raise ExternalDataError("未配置 Google 地理编码", validation=True)

    cities = []
    failures: list[ExternalDataError] = []
    today = live.evaluation_today or tokyo_today()
    for segment in segments:
        if segment.depart < today or segment.arrive > today + timedelta(days=15):
            result: dict[str, object] = {"status": "unknown", "reason": "超出 16 天预报范围"}
        else:
            try:
                point = await live.google.geocode(segment.city)
                result = await forecast(
                    live.http,
                    live.usage,
                    point,
                    segment_request(request, segment),
                    data_mode=live.data_mode,
                    today=today,
                )
            except ExternalDataError as error:
                failures.append(error)
                result = {"status": "unknown", "reason": "该城天气暂不可用"}
        cities.append({"city": segment.city, **result})
    if len(failures) == len(segments):
        raise failures[0]
    if len(cities) == 1:
        return cities[0]
    states = {city["status"] for city in cities}
    state = (
        "verified" if states == {"verified"} else "unknown" if states == {"unknown"} else "partial"
    )
    return {"status": state, "cities": cities}


async def cached_rain(
    db: AsyncSession, request: TravelRequest, now: datetime, today: date | None = None
) -> dict[tuple[str, date], int | None]:
    if request.start_date is None or request.end_date is None:
        return {}
    today = today or tokyo_today()
    start = max(request.start_date, today)
    end = min(request.end_date, today + timedelta(days=15))
    if end < start:
        return {}
    cities = {city_key(segment.city) for segment in trip_segments(request)}
    rows = await db.scalars(
        select(WeatherForecastRow)
        .where(
            WeatherForecastRow.city.in_(cities),
            WeatherForecastRow.start_date <= end,
            WeatherForecastRow.end_date >= start,
            WeatherForecastRow.fetched_at > now - timedelta(hours=3),
        )
        .order_by(WeatherForecastRow.fetched_at)
    )
    rain: dict[tuple[str, date], int | None] = {}
    for row in rows:
        days = row.payload.get("days")
        if not isinstance(days, list):
            continue
        for item in days:
            if not isinstance(item, dict) or not isinstance(item.get("date"), str):
                continue
            try:
                day = date.fromisoformat(item["date"])
            except ValueError:
                continue
            chance = item.get("rain_probability")
            if start <= day <= end:
                rain[(row.city, day)] = (
                    chance if type(chance) is int and 0 <= chance <= 100 else None
                )
    return rain

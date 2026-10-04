"""Open-Meteo 的16天预报；超出范围保持未知，不以历史天气替代。"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel

from backend.adapters.external_api import ApiUsage, parse_response, request_json
from backend.domain.external_data import ExternalDataError, GeoPoint
from backend.domain.travel_request import TravelRequest


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
    http: httpx.AsyncClient, usage: ApiUsage, point: GeoPoint, request: TravelRequest
) -> dict[str, object]:
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    if not request.start_date or not request.end_date:
        return {"status": "unknown", "reason": "旅行日期尚未确定"}
    if request.start_date < today or request.end_date > today + timedelta(days=15):
        return {"status": "unknown", "reason": "旅行日期超出16天预报范围，临近出行再查询"}
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
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
            },
        ),
    ).daily
    columns = (
        data.weather_code,
        data.temperature_2m_max,
        data.temperature_2m_min,
        data.precipitation_probability_max,
    )
    if any(len(column) != len(data.time) for column in columns):
        raise ExternalDataError("天气响应字段长度不匹配")
    return {
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
        "source_ref": "https://open-meteo.com/",
        "attribution": "Open-Meteo.com (CC BY 4.0)",
    }

"""合成HTTP+真实PG验证少量正常/失败及计数事务；不发任何真实API调用。"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from backend.adapters.external_api import ApiUsage, request_json
from backend.adapters.google_maps import GoogleMaps
from backend.adapters.live_data import LiveData
from backend.adapters.open_meteo import forecast
from backend.adapters.rakuten import Rakuten
from backend.domain.execution import RunContext
from backend.domain.external_data import ExternalDataError, GeoPoint
from backend.domain.travel_request import TravelRequest
from backend.persistence.catalog import import_catalog
from backend.persistence.models import EvidenceRow, WeatherForecastRow
from backend.services.catalog import CatalogService
from backend.services.common import ServiceError, transaction
from backend.services.plans import PlanService
from backend.services.travel import TravelService
from backend.tools.search import PlaceSearchInput
from data.import_catalog import load_snapshot
from tests.integration.test_plans import initial_draft
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_external_data import sample
from tests.test_hotels import request as hotel_request

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("times", [[], ["2000-01-01"]])
def test_weather_empty_or_wrong_dates_are_not_cached(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], times: list[str]
) -> None:
    runner, travel, _ = travel_setup
    today = datetime.now(UTC).date() + timedelta(days=2)
    request = TravelRequest(city="合成空天气", start_date=today, end_date=today)
    point = GeoPoint(name="合成空天气", latitude=35, longitude=135)
    payload = {
        "daily": {
            "time": times,
            "weather_code": [0] * len(times),
            "temperature_2m_max": [20] * len(times),
            "temperature_2m_min": [10] * len(times),
            "precipitation_probability_max": [0] * len(times),
        }
    }

    async def exercise() -> None:
        usage = ApiUsage(travel.database, {})
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ) as http:
            with pytest.raises(ExternalDataError, match="日期范围"):
                await forecast(http, usage, point, request)
        async with travel.database.sessions.begin() as db:
            assert await db.get(WeatherForecastRow, ("合成空天气", today, today)) is None
            await db.execute(
                text("UPDATE external_api_usage SET calls=calls-1 WHERE api='weather'")
            )

    runner.run(exercise())


def test_weather_cache_survives_new_run_and_expires_after_three_hours(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, _ = travel_setup
    today = datetime.now(UTC).date() + timedelta(days=1)
    request = TravelRequest(city="京都", start_date=today, end_date=today + timedelta(days=1))
    point = GeoPoint(name="京都", latitude=35, longitude=135)
    payload = {
        "daily": {
            "time": [today.isoformat(), (today + timedelta(days=1)).isoformat()],
            "weather_code": [0, 61],
            "temperature_2m_max": [20, 18],
            "temperature_2m_min": [10, 9],
            "precipitation_probability_max": [0, 70],
        }
    }

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ) as http:
            first = ApiUsage(travel.database, {})
            result = await forecast(http, first, point, request)
            second = ApiUsage(travel.database, {})
            assert await forecast(http, second, point, request) == result
            assert first.used == {"weather": 1} and second.used == {}
            async with travel.database.sessions.begin() as db:
                cached = await db.get(WeatherForecastRow, ("京都", today, request.end_date))
                assert cached
                cached.fetched_at -= timedelta(hours=3, seconds=1)
            await forecast(http, second, point, request)
            assert second.used == {"weather": 1}
        # postgres_url 是隔离测试库；还原本测试新增计数，不影响既有配额反例。
        async with travel.database.sessions.begin() as db:
            await db.execute(
                text("UPDATE external_api_usage SET calls=calls-2 WHERE api='weather'")
            )

    runner.run(exercise())


def test_rakuten_two_night_totals_and_one_refresh_cap(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, _ = travel_setup

    def respond(request: httpx.Request) -> httpx.Response:
        # 同一房型与方案，每晚价格按真实响应的 stayDate 匹配。
        payload = json.dumps(sample()).replace("2026-11-06", request.url.params["checkinDate"])
        return httpx.Response(200, content=payload)

    async def exercise() -> None:
        usage = ApiUsage(travel.database, {})
        original = hotel_request()
        assert original.end_date
        request = original.model_copy(update={"end_date": original.end_date - timedelta(days=1)})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            provider = Rakuten("test", "test", "", "", http, usage)
            point = GeoPoint(name="京都", latitude=35, longitude=135)
            offers = await provider.search(request, point)
            assert offers[0].included_total == 20000
            assert usage.run_caps["rakuten"] == 3 and usage.used == {"rakuten": 2}
            with pytest.raises(ExternalDataError, match="本轮.*上限"):
                await provider.search(request, point)
            assert usage.used == {"rakuten": 3}

    runner.run(exercise())


def test_request_counter_commits_failure_and_blocks_second_request(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, _ = travel_setup

    async def exercise() -> None:
        usage = ApiUsage(travel.database, {"WEATHER_DAILY_CAP": "1"})
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(429))
        ) as http:
            with pytest.raises(ExternalDataError, match="429"):
                await request_json(http, usage, "weather", "GET", "https://example.test")
            with pytest.raises(ExternalDataError, match="上限"):
                await request_json(http, usage, "weather", "GET", "https://example.test")
        async with transaction(travel.database) as db:
            assert (
                await db.scalar(
                    text("SELECT calls FROM external_api_usage WHERE day=:day AND api='weather'"),
                    {"day": datetime.now(UTC).date()},
                )
                == 1
            )

    runner.run(exercise())


def test_timeout_is_safe_and_is_counted(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, _ = travel_setup

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret-bearing upstream message", request=request)

    async def exercise() -> None:
        usage = ApiUsage(travel.database, {})
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as http:
            with pytest.raises(ExternalDataError, match="请求超时") as failure:
                await request_json(http, usage, "weather", "GET", "https://example.test")
            assert "secret-bearing" not in str(failure.value)
        assert usage.used == {"weather": 1}

    runner.run(exercise())


def test_places_normal_response_persists_only_ids_and_coordinates(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    def respond(request: httpx.Request) -> httpx.Response:
        if "geocode" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "results": [
                        {
                            "place_id": "city-test",
                            "address_components": [
                                {"long_name": "日本", "short_name": "JP", "types": ["country"]}
                            ],
                            "geometry": {"location": {"lat": 35, "lng": 135}},
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "synthetic",
                        "displayName": {"text": "合成景点名称"},
                        "location": {"latitude": 35, "longitude": 135},
                    }
                ]
            },
        )

    async def exercise() -> None:
        usage = ApiUsage(travel.database, {})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            live = LiveData(GoogleMaps("test", http, usage), None, usage, http, {})
            travel.live = live
            async with transaction(travel.database) as db:
                await import_catalog(db, load_snapshot())
            result = await CatalogService(travel).query(
                context, PlaceSearchInput(city="京都", limit=1)
            )
            assert result.rows[0]["name"] == "合成景点名称"
            async with transaction(travel.database) as db:
                stored = await db.get(EvidenceRow, result.evidence[0].evidence_id)
                assert stored and stored.payload["value"] == {
                    "place_id": "gplace:synthetic",
                    "city": "京都",
                }
                assert "合成景点名称" not in str(stored.payload)
            resolved = await travel.resolve_evidence(context, (result.evidence[0].evidence_id,))
            assert resolved[0].value == result.evidence[0].value
            assert usage.used == {"geocode": 1, "places": 1}

    runner.run(exercise())


def test_calendar_confirmed_plan_and_other_user(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        draft = await initial_draft(travel, context)
        service = PlanService(travel)
        saved = await service.confirm(context.user_id, draft.draft_id)
        content, version = await service.calendar(context.user_id, saved.plan_id)
        assert version == 1 and content.count("BEGIN:VEVENT") == len(saved.content.items)
        assert "DTSTART:20261103" in content and "Z\r\n" in content
        with pytest.raises(ServiceError, match="不存在"):
            await service.calendar(uuid4(), saved.plan_id)

    runner.run(exercise())

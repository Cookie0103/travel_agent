"""合成HTTP+真实PG验证少量正常/失败及计数事务；不发任何真实API调用。"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from backend.adapters.external_api import ApiUsage, request_json
from backend.adapters.google_maps import GoogleMaps
from backend.adapters.live_data import LiveData
from backend.domain.execution import RunContext
from backend.domain.external_data import ExternalDataError
from backend.persistence.catalog import import_catalog
from backend.persistence.models import EvidenceRow
from backend.services.catalog import CatalogService
from backend.services.common import ServiceError, transaction
from backend.services.plans import PlanService
from backend.services.travel import TravelService
from backend.tools.search import PlaceSearchInput
from data.import_catalog import load_snapshot
from tests.integration.test_plans import initial_draft
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


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

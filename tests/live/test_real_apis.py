"""手动选一个供应商接口探针；默认不运行，不更新或持久录制原始响应。"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from dotenv import load_dotenv

from backend.adapters.external_api import ApiName
from backend.adapters.live_data import LiveData
from backend.adapters.open_meteo import forecast
from backend.domain.catalog import Place
from backend.domain.external_data import GeoPoint
from backend.domain.travel_request import TravelRequest
from backend.persistence.database import Database, configuration, database_url
from data.import_catalog import load_snapshot
from scripts.dev import ROOT

pytestmark = pytest.mark.live


def test_single_real_api() -> None:
    selected = os.environ.get("TRAVEL_REAL_API_PROBE", "")
    if selected not in {"geocode", "places", "routes", "rakuten", "weather"}:
        pytest.skip("显式指定 TRAVEL_REAL_API_PROBE；每次只测一个接口，禁止CI或循环执行")
    load_dotenv(ROOT / ".env", encoding="utf-8")
    api = cast(ApiName, selected)

    async def exercise() -> None:
        database = Database(database_url(configuration()))
        live = LiveData.from_environment(os.environ, database)
        try:
            assert live.google, "未配置 Google Maps"
            request = TravelRequest(
                city="大阪",
                start_date=datetime.now(UTC).date() + timedelta(days=2),
                end_date=datetime.now(UTC).date() + timedelta(days=3),
                adults=2,
                rooms=1,
                child_ages=(),
            )
            # 大阪市中心是已知探针输入；非地理编码分支不额外发前置请求。
            point = GeoPoint(name="大阪", latitude=34.6937, longitude=135.5023)
            live.google.points["大阪"] = point
            if selected == "geocode":
                live.google.points.clear()
                point = await live.google.geocode("大阪")
                assert 20 < point.latitude < 46 and 122 < point.longitude < 154
            elif selected == "places":
                places = await live.google.search_places("大阪", "美术馆", 3)
                assert places and places[0].place_id and places[0].name
            elif selected == "routes":
                # 公开 OSM 坐标作路线输入；不额外请求 Google 地点详情。
                entries = [item for item in load_snapshot() if isinstance(item, Place)]
                route = await live.google.route(
                    Place.model_validate(entries[0]),
                    Place.model_validate(entries[1]),
                    "walk",
                    datetime.now(UTC) + timedelta(days=2),
                    2,
                )
                assert route.minutes is not None
            elif selected == "rakuten":
                assert live.rakuten, "未配置乐天"
                assert await live.rakuten.search(request, point, limit=2)
            else:
                result = await forecast(live.http, live.usage, point, request)
                assert result["status"] == "verified" and result["days"]
            assert live.usage.used.get(api, 0) <= 1 and sum(live.usage.used.values()) <= 1
            print(f"probe={selected}, status=passed, calls={live.usage.used}")
        finally:
            await live.close()
            await database.close()

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(exercise())

"""介绍页缺失不能删除可用报价和独立套餐/预订链接。"""

import asyncio
from datetime import date

import httpx
import pytest

from backend.adapters.rakuten import Rakuten
from backend.domain.external_data import GeoPoint
from tests.test_external_data import _CountingUsage, sample
from tests.test_hotel_links import URLS
from tests.test_hotels import request


@pytest.mark.parametrize("mode", ["missing", "null", "all_missing"])
def test_missing_info_link_keeps_available_quote(mode: str) -> None:
    async def exercise() -> None:
        payload = sample()
        entries = payload["hotels"]
        assert isinstance(entries, list) and isinstance(entries[0], list)
        basic = entries[0][0]
        rooms = entries[0][1]
        assert isinstance(basic, dict) and isinstance(rooms, dict)
        info = basic["hotelBasicInfo"]
        room_info = rooms["roomInfo"]
        assert isinstance(info, dict) and isinstance(room_info, list)
        assert isinstance(room_info[0], dict)
        room = room_info[0]["roomBasicInfo"]
        assert isinstance(room, dict)
        info.pop("hotelInformationUrl")
        if mode == "null":
            info["hotelInformationUrl"] = None
        if mode != "all_missing":
            info["planListUrl"] = URLS["plan_list_url"]
            room["reserveUrl"] = URLS["reservation_url"]
        trip = request().model_copy(update={"end_date": date(2026, 11, 7)})
        usage = _CountingUsage({})
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ) as http:
            found = await Rakuten("test", "test", "", "", http, usage).search(
                trip, GeoPoint(name="京都", latitude=35, longitude=135), limit=1
            )
        assert len(found) == 1 and found[0].total == 10000 and usage.calls == 1
        details = found[0].display_details
        assert details and details.hotel_info_url is None
        assert details.plan_list_url == (None if mode == "all_missing" else URLS["plan_list_url"])
        assert details.reservation_url == (
            None if mode == "all_missing" else URLS["reservation_url"]
        )
        assert found[0].booking_url == (None if mode == "all_missing" else URLS["reservation_url"])

    asyncio.run(exercise())

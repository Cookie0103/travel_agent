"""三类供应商链接保留原义，内部展示细节不进入旧报价/供应商协议。"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from backend.adapters.rakuten import Rakuten
from backend.domain.booking import Booking, HoldInput, SupplierHold
from backend.domain.external_data import GeoPoint
from backend.domain.hotels import HotelOffer
from tests.fixtures.legacy_hotel_offer_v1 import HotelOffer as LegacyOffer
from tests.test_external_data import _CountingUsage, sample
from tests.test_hotels import offer, request

URLS = {
    "hotel_info_url": "https://example.com/hotel-info",
    "plan_list_url": "https://example.com/hotel-plans",
    "reservation_url": "https://example.com/hotel-reserve",
}


@pytest.mark.parametrize("missing", [False, True])
def test_adapter_preserves_three_urls_without_guessing_missing_links(missing: bool) -> None:
    async def exercise() -> None:
        payload = sample()
        hotels = payload["hotels"]
        assert isinstance(hotels, list) and isinstance(hotels[0], list)
        basic = hotels[0][0]
        rooms = hotels[0][1]
        assert isinstance(basic, dict) and isinstance(rooms, dict)
        info = basic["hotelBasicInfo"]
        room_info = rooms["roomInfo"]
        assert isinstance(info, dict) and isinstance(room_info, list)
        assert isinstance(room_info[0], dict)
        room = room_info[0]["roomBasicInfo"]
        assert isinstance(room, dict)
        info["hotelInformationUrl"] = URLS["hotel_info_url"]
        if not missing:
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
        assert len(found) == 1 and usage.calls == 1
        details = found[0].display_details
        assert details is not None
        assert details.hotel_info_url == URLS["hotel_info_url"]
        assert details.plan_list_url == (None if missing else URLS["plan_list_url"])
        assert details.reservation_url == (None if missing else URLS["reservation_url"])
        assert found[0].booking_url == URLS["hotel_info_url" if missing else "reservation_url"]

    asyncio.run(exercise())


def test_internal_display_fields_never_enter_nested_legacy_quote_snapshots() -> None:
    source = offer()
    detailed = HotelOffer.model_validate({**source.model_dump(), "display_details": URLS})
    assert detailed.display_details is not None
    snapshots = [
        detailed.model_dump(mode="json"),
        HoldInput(client_ref=uuid4(), offer=detailed).model_dump(mode="json")["offer"],
        SupplierHold(
            client_ref=uuid4(),
            offer=detailed,
            hold_id=uuid4(),
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
        ).model_dump(mode="json")["offer"],
        Booking.quoted(uuid4(), uuid4(), detailed, "fixture:test", "v1").model_dump(mode="json")[
            "offer"
        ],
    ]
    for snapshot in snapshots:
        restored = LegacyOffer.model_validate(snapshot)
        assert restored.offer_id == source.offer_id and restored.base_amount == source.base_amount
    assert "display_details" not in detailed.model_json_schema(mode="serialization")["properties"]
    assert source.display_details is None

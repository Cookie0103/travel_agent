"""现有供应商响应结构：展示元数据不影响报价、调用与顺序。"""

import asyncio
from datetime import date

import httpx
import pytest
from pydantic import JsonValue, ValidationError

from backend.adapters.rakuten import Rakuten
from backend.domain.external_data import GeoPoint
from backend.domain.hotel_details import HotelMetadata
from tests.test_external_data import _CountingUsage, sample
from tests.test_hotels import request


@pytest.mark.parametrize(
    "fields,expected",
    [
        (
            {
                "address1": "京都府京都市",
                "address2": "下京区合成町1",
                "latitude": 34.9851,
                "longitude": 135.7587,
                "reviewCount": 123,
            },
            ("京都府京都市下京区合成町1", 34.9851, 135.7587, 123),
        ),
        ({"address1": "京都府京都市", "reviewCount": 0}, ("京都府京都市", None, None, 0)),
        (
            {"address2": "下京区合成町1", "latitude": 0, "longitude": 0},
            ("下京区合成町1", 0, 0, None),
        ),
        ({"address1": "", "address2": ""}, (None, None, None, None)),
        (
            {
                "address1": None,
                "address2": None,
                "latitude": None,
                "longitude": None,
                "reviewCount": None,
            },
            (None, None, None, None),
        ),
        ({}, (None, None, None, None)),
    ],
)
def test_response_metadata_keeps_values_and_unknowns_without_new_queries(
    fields: dict[str, JsonValue],
    expected: tuple[str | None, float | None, float | None, int | None],
) -> None:
    async def exercise() -> None:
        payload = sample()
        hotels = payload["hotels"]
        assert isinstance(hotels, list) and isinstance(hotels[0], list)
        first = hotels[0][0]
        assert isinstance(first, dict)
        basic = first["hotelBasicInfo"]
        assert isinstance(basic, dict)
        basic.update(fields)
        trip = request().model_copy(update={"end_date": date(2026, 11, 7)})
        usage = _CountingUsage({})

        def respond(query: httpx.Request) -> httpx.Response:
            assert query.url.params["datumType"] == "1"
            assert query.url.params["responseType"] == "large"
            assert "sort" not in query.url.params
            return httpx.Response(200, json=payload)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            found = await Rakuten("test", "test", "", "", http, usage).search(
                trip,
                GeoPoint(name="京都", latitude=35, longitude=135),
                limit=1,
            )
        assert len(found) == 1 and usage.calls == 1
        assert found[0].hotel_id == "1" and found[0].total == 10000
        details = found[0].display_details
        assert details is not None
        assert (
            details.address,
            details.latitude,
            details.longitude,
            details.review_count,
        ) == expected
        assert "display_details" not in found[0].model_dump(mode="json")

    asyncio.run(exercise())


@pytest.mark.parametrize("key", ["hotel_info_url", "base_amount", "offer_id"])
def test_metadata_column_cannot_override_links_prices_or_identity(key: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        HotelMetadata.model_validate({key: "untrusted"})

"""覆盖探针只落脱敏样本，离线重放现有多晚适配器。"""

import asyncio
import copy

import pytest
from pydantic import JsonValue

from scripts.probe_hotel_coverage import replay_two_nights, sanitize_payload, trip
from tests.test_external_data import fixture
from tests.test_rakuten_discovery import HOTEL_0, entries, room_parts


def test_probe_recursively_removes_urls_and_credential_keys() -> None:
    payload: dict[str, JsonValue] = {
        "hotels": [
            {
                "HotelImageURL": "secret",
                "name": "hotel",
                "nested": {
                    "applicationId": "secret",
                    "accessKey": "secret",
                    "reviewCount": 0,
                },
            }
        ],
    }
    assert sanitize_payload(payload, ("secret",)) == {
        "hotels": [{"name": "hotel", "nested": {"reviewCount": 0}}],
    }


def test_probe_refuses_credentials_hidden_in_remaining_text() -> None:
    with pytest.raises(ValueError, match="credential"):
        sanitize_payload({"hotelSpecial": "unexpected test-secret in text"}, ("test-secret",))


@pytest.mark.parametrize("key", ["unexpected_abc/123", "unexpected_abc%2F123"])
def test_probe_refuses_credentials_hidden_in_remaining_keys(key: str) -> None:
    with pytest.raises(ValueError, match="credential"):
        sanitize_payload({key: "public"}, ("abc/123",))


def test_two_night_replay_keeps_mismatched_plan_total_unknown() -> None:
    first = fixture(HOTEL_0)
    second = copy.deepcopy(first)
    for hotel in entries(second):
        for room in room_parts(hotel):
            if "dailyCharge" in room:
                room["dailyCharge"]["stayDate"] = "2026-10-12"
    for room in room_parts(entries(second)[0]):
        if "roomBasicInfo" in room:
            room["roomBasicInfo"]["planId"] = 123
    result = asyncio.run(replay_two_nights(trip("那霸", "2026-10-11", nights=2), first, second))
    assert result["shown"] == 5 and result["complete_totals"] == 4
    assert result["unknown_totals"] == 1 and result["replay_requests"] == 2

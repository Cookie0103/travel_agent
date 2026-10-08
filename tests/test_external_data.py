"""V2必要纯规则：结构错误、营业期、报价未知、事件引用和日历编码。"""

import asyncio
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from pydantic import JsonValue, TypeAdapter

from backend.adapters.external_api import ApiUsage
from backend.adapters.google_maps import (
    GoogleMaps,
    _Hours,
    _Places,
    broad_region,
    opening_hours,
)
from backend.adapters.open_meteo import Forecast
from backend.adapters.rakuten import Candidate, Rakuten, candidates
from backend.domain.execution import RunContext, RuntimeEvent, event_metadata
from backend.domain.external_data import ExternalDataError, GeoPoint
from backend.domain.opening_hours import opening_state
from backend.domain.travel_request import TravelRequest
from backend.services.calendar import escape, fold
from tests.test_hotels import request


@pytest.mark.parametrize(
    "city,broad",
    [
        ("札幌", False),
        ("大阪", False),
        ("那霸", False),
        ("箱根", False),
        ("北海道", True),
        ("冲绳", True),
    ],
)
def test_concrete_city_is_not_rejected_for_large_area(city: str, broad: bool) -> None:
    assert broad_region(city) is broad


def test_multiple_opening_periods_and_full_day() -> None:
    hours = _Hours.model_validate(
        {
            "periods": [
                {"open": {"day": 1, "hour": 9}, "close": {"day": 1, "hour": 12}},
                {"open": {"day": 1, "hour": 13}, "close": {"day": 1, "hour": 17}},
            ]
        }
    )
    value = opening_hours(hours)
    assert value == "Mo 09:00-12:00,13:00-17:00"
    assert (
        opening_state(
            value,
            datetime.fromisoformat("2026-10-05T10:00+09:00"),
            datetime.fromisoformat("2026-10-05T11:00+09:00"),
        )
        == "open"
    )
    assert (
        opening_hours(
            _Hours.model_validate({"periods": [{"open": {"day": 1}, "close": {"day": 2}}]})
        )
        == "Mo 00:00-24:00"
    )
    assert opening_hours(None) is None


def sample() -> dict[str, JsonValue]:
    return fixture("rakuten_vacant_sample.json")


def fixture(name: str) -> dict[str, JsonValue]:
    return TypeAdapter(dict[str, JsonValue]).validate_json(
        (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")
    )


def test_synthetic_supplier_samples_parse_without_network() -> None:
    assert _Places.model_validate(fixture("google_places_sample.json")).places[0].id
    assert Forecast.model_validate(fixture("open_meteo_sample.json")).daily.weather_code == [61]
    assert fixture("google_routes_sample.json")["routes"]


def test_rakuten_first_night_charge_units_and_missing_date() -> None:
    candidate = candidates(sample())[0]
    assert Rakuten.price(candidate, request(), date(2026, 11, 6)) == Decimal(10000)
    assert Rakuten.price(candidate, request(), date(2026, 11, 7)) is None
    assert candidates({"hotels": []}) == ()
    with pytest.raises(ExternalDataError):
        candidates({"hotels": [{}]})


def test_event_storage_keeps_ui_wrapper_and_refs_without_google_cards() -> None:
    context = RunContext(uuid4())
    draft = str(uuid4())
    event = event_metadata(
        RuntimeEvent(
            context,
            "presentation",
            text="Google返回名称",
            presentation={"data": {"draft_id": draft, "cards": [{"name": "Google返回名称"}]}},
        )
    )
    assert event.text == "" and event.presentation == {"data": {"draft_id": draft}}
    hotel = RuntimeEvent(
        context,
        "presentation",
        presentation={"data": {"component": "hotel_comparison", "cards": []}},
    )
    assert event_metadata(hotel).presentation == hotel.presentation


def test_calendar_text_escaping_and_utf8_folding() -> None:
    assert escape("a,b;c\\d\r\ne") == r"a\,b\;c\\d\ne"
    lines = fold("SUMMARY:" + "旅行" * 100).split("\r\n")
    assert all(len(line.encode("utf-8")) <= 75 for line in lines)
    assert all(line.startswith(" ") for line in lines[1:])


class _CountingUsage(ApiUsage):
    """不连数据库：只计外部调用次数。"""

    def __init__(self, env: dict[str, str]) -> None:
        super().__init__(cast(Any, None), env)
        self.calls = 0

    async def consume(self, api: str) -> None:
        self.calls += 1


def test_google_place_details_is_cached_after_first_fetch() -> None:
    body = {
        "id": "synthetic-place",
        "displayName": {"text": "合成美术馆"},
        "location": {"latitude": 35, "longitude": 135},
        "types": ["museum"],
    }

    async def exercise() -> None:
        usage = _CountingUsage({})
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as http:
            google = GoogleMaps("test", http, usage)
            first = await google.details("gplace:synthetic-place", "京都")
            second = await google.details("gplace:synthetic-place", "京都")
        assert first.name == second.name == "合成美术馆" and usage.calls == 1

    asyncio.run(exercise())


def test_google_place_details_failure_is_not_cached() -> None:
    async def exercise() -> None:
        usage = _CountingUsage({})
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(500, json={}))
        ) as http:
            google = GoogleMaps("test", http, usage)
            for _ in range(2):
                with pytest.raises(ExternalDataError):
                    await google.details("gplace:missing", "京都")
        assert usage.calls == 2 and not google.places

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "env,expected",
    [({}, 2), ({"TRAVEL_PROFILE": "relaxed"}, 20), ({"TRAVEL_PROFILE": "human"}, 30)],
)
def test_rakuten_run_cap_default_follows_nights_and_other_profiles_keep_config(
    env: dict[str, str], expected: int
) -> None:
    async def exercise() -> None:
        usage = _CountingUsage(env)
        trip = request().model_copy(update={"end_date": date(2026, 11, 7)})  # 1晚
        async with httpx.AsyncClient() as http:
            provider = Rakuten("test", "test", "", "", http, usage)
            point = GeoPoint(name="京都", latitude=35, longitude=135, broad=True)
            with pytest.raises(ExternalDataError, match="区域过大"):
                await provider.search(trip, point)
        assert usage.run_caps["rakuten"] == expected and usage.calls == 0

    asyncio.run(exercise())


def test_google_missing_place_types_remain_unknown_instead_of_inventing_attraction() -> None:
    from backend.adapters.google_maps import place_from_response

    response = fixture("google_places_sample.json")
    assert isinstance(response, dict) and isinstance(response["places"], list)
    entry = response["places"][0]
    assert isinstance(entry, dict)
    raw = dict(entry)
    raw.pop("types", None)
    parsed = _Places.model_validate({"places": [raw]}).places[0]
    mapped = place_from_response(parsed, "京都")
    assert mapped.category == "unknown"
    assert mapped.name == parsed.displayName.text
    assert mapped.latitude == parsed.location.latitude


def test_rakuten_limit_covers_distinct_hotels_without_extra_nightly_calls() -> None:
    seed = candidates(sample())[0]
    rows = tuple(
        seed.model_copy(
            update={
                "hotel": seed.hotel.model_copy(update={"hotelNo": hotel}),
                "room": seed.room.model_copy(update={"planId": plan}),
            }
        )
        for hotel, plan in [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (3, 1), (3, 2), (4, 1), (5, 1)]
    )
    calls: list[tuple[int, ...]] = []

    class ControlledRakuten(Rakuten):
        async def nightly(
            self,
            request: TravelRequest,
            day: date,
            point: GeoPoint,
            hotel_ids: tuple[int, ...] = (),
        ) -> tuple[Candidate, ...]:
            calls.append(hotel_ids)
            return tuple(
                row.model_copy(update={"charge": seed.charge.model_copy(update={"stayDate": day})})
                for row in rows
                if seed.charge and (not hotel_ids or row.hotel.hotelNo in hotel_ids)
            )

    async def exercise() -> None:
        usage = _CountingUsage({})
        async with httpx.AsyncClient() as http:
            provider = ControlledRakuten("test", "test", "", "", http, usage)
            result = await provider.search(
                request(), GeoPoint(name="京都", latitude=35, longitude=135), limit=4
            )
        assert [offer.hotel_id for offer in result] == ["1", "1", "2", "2", "3", "4"]
        assert len(result) == 6 and all(offer.total == Decimal(30000) for offer in result)
        assert calls == [(), (1, 2, 3, 4), (1, 2, 3, 4)]

    asyncio.run(exercise())

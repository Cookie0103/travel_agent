"""V2必要纯规则：结构错误、营业期、报价未知、事件引用和日历编码。"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import JsonValue, TypeAdapter

from backend.adapters.google_maps import _Hours, _Places, broad_region, opening_hours
from backend.adapters.open_meteo import Forecast
from backend.adapters.rakuten import Rakuten, candidates
from backend.domain.execution import RunContext, RuntimeEvent, event_metadata
from backend.domain.external_data import ExternalDataError
from backend.domain.opening_hours import opening_state
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

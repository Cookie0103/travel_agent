"""第二版题库合成世界合同，供应商请求全部留在内存。"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from backend.adapters.evaluation_faults import fault_transport
from backend.adapters.evaluation_places import city_places
from backend.adapters.evaluation_world import EvaluationCity, EvaluationWorld, serve
from backend.adapters.rakuten import Candidate, Rakuten, candidates
from backend.domain.external_data import GeoPoint
from backend.domain.geo import haversine_m
from backend.domain.room_preferences import room_assessment
from backend.domain.travel_request import TravelRequest
from data.eval_world.world import World, load_world
from eval.core.evaluation_world import phase2_world
from tests.unit.adapters.test_external_data import _CountingUsage

RAIN_STARTS = (
    date(2026, 11, 10),
    date(2026, 11, 27),
    date(2026, 12, 8),
    date(2026, 12, 19),
    date(2027, 1, 9),
)
RAIN_DAYS = {start + timedelta(days=offset) for start in RAIN_STARTS for offset in range(3)}


def test_phase2_synthetic_weather_calendar_covers_city_and_window_boundaries() -> None:
    world = phase2_world()
    assert world.today == date(2026, 10, 24)
    first = RAIN_STARTS[0] - timedelta(days=1)
    last = RAIN_STARTS[-1] + timedelta(days=3)
    days = [first + timedelta(days=offset) for offset in range((last - first).days + 1)]
    transport = fault_transport(
        "phase2-world",
        profile="eval",
        database_dsn=f"postgresql://localhost/travel_agent_eval_{'a' * 32}",
        world=world,
    )
    with httpx.Client(transport=transport) as client:
        for city in world.cities:
            result = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": city.latitude,
                    "longitude": city.longitude,
                    "start_date": first.isoformat(),
                    "end_date": last.isoformat(),
                },
            ).json()["daily"]
            assert result["time"] == [day.isoformat() for day in days]
            assert all(
                (80 <= chance <= 100 if day in RAIN_DAYS else 0 <= chance <= 10)
                for day, chance in zip(days, result["precipitation_probability_max"], strict=True)
            ), city.city
            assert result["weather_code"] == [61 if day in RAIN_DAYS else 0 for day in days]


def test_phase2_v2_named_places_and_reservation_windows() -> None:
    world = phase2_world()
    catalog = {
        item.name: item
        for city in world.cities
        for item in city_places(city.city, city.latitude, city.longitude)
    }
    for name, expected in {
        "桂離宮": (9 * 60, 16 * 60, 1),
        "三鷹の森ジブリ美術館": (10 * 60, 18 * 60, 2),
    }.items():
        place = catalog[name]
        assert (place.open_minute, place.close_minute, place.closed_day) == expected
    ghibli = catalog["三鷹の森ジブリ美術館"]
    assert "三鹰之森吉卜力美术馆" in ghibli.aliases
    ueno = catalog["上野動物園"]
    assert not ueno.category.indoor and ueno.closed_day == 1
    assert catalog["海遊館"].category.indoor and catalog["海遊館"].closed_day is None
    for name in ("清水寺", "大阪城", "東大寺", "奈良公園"):
        assert not catalog[name].category.indoor and catalog[name].closed_day is None
    for name in ("大通公園", "太宰府天満宮", "大濠公園"):
        assert not catalog[name].category.indoor
    assert "白い恋人パーク" in catalog
    for city in world.cities:
        places = city_places(city.city, city.latitude, city.longitude)
        assert (
            sum(
                item.category.indoor and item.category.code not in {"restaurant", "cafe"}
                for item in places
            )
            >= 6
        )
        assert any(
            item.response().get("evaluationReservationRequired")
            and item.name not in {"桂離宮", "三鷹の森ジブリ美術館"}
            for item in places
        )
        assert any(item.name.startswith("合成") and item.closed_day is not None for item in places)
        assert any(item.name.startswith("合成") and item.close_minute < 990 for item in places)


def search(
    world: EvaluationWorld, city: EvaluationCity, day: str, adults: int
) -> tuple[tuple[Candidate, ...], int]:
    request = httpx.Request(
        "GET",
        "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426",
        params={
            "latitude": city.latitude,
            "longitude": city.longitude,
            "checkinDate": day,
            "adultNum": adults,
        },
    )
    response = serve(request, world)
    assert response is not None
    payload = response.json()
    return candidates(payload), int(payload["pagingInfo"]["recordCount"])


@pytest.mark.parametrize(
    "day,normal_demand", [("2026-11-10", True), ("2026-11-13", True), ("2026-11-23", False)]
)
@pytest.mark.parametrize("adults", [1, 2])
def test_phase2_v2_hotel_market_meets_each_city_threshold(
    day: str, normal_demand: bool, adults: int
) -> None:
    world = phase2_world()
    for city in world.cities:
        rows, count = search(world, city, day, adults)
        assert 12 <= count == len(rows) <= 20
        prices = []
        distances = []
        breakfasts = []
        ratings = []
        partners = []
        family_rooms = []
        for offer in rows:
            assert offer.charge is not None and offer.charge.chargeFlag == 1
            prices.append(offer.charge.rakutenCharge)
            hotel = offer.hotel
            assert hotel.latitude is not None and hotel.longitude is not None
            distances.append(
                haversine_m(city.latitude, city.longitude, hotel.latitude, hotel.longitude)
            )
            breakfasts.append(offer.room.withBreakfastFlag == 1)
            ratings.append(hotel.reviewAverage or 0)
            partners.append(hotel.evaluationPartner)
            if "家庭房" in room_assessment(offer.room.roomName, None).room_tags:
                family_rooms.append(offer)
                assert offer.charge.rakutenCharge <= 30000
                assert any(
                    term in offer.room.roomName for term in ("家庭", "ファミリー", "トリプル")
                )
        assert min(prices) >= 6000
        if normal_demand:
            assert sum(value <= 10000 for value in prices) >= 5, city.city
            assert sum(value <= 14000 for value in prices) >= 8, city.city
        assert sum(breakfasts) >= 6
        assert sum(value <= 500 for value in distances) >= 4
        assert (
            sum(breakfast and d <= 800 for breakfast, d in zip(breakfasts, distances, strict=True))
            >= 3
        )
        assert sum(value >= 4.4 for value in ratings) >= 4
        assert sum(value >= 4.3 for value in ratings) >= 6
        assert len(family_rooms) >= 4
        assert any(offer.room.evaluationMaxGuests == 4 for offer in family_rooms)
        assert sum(partners) >= 3
        assert any(
            partner and breakfast and price <= 18000
            for partner, breakfast, price in zip(partners, breakfasts, prices, strict=True)
        )


@pytest.mark.parametrize(
    "adults,children,rooms,total",
    [(5, (), 3, Decimal(39000)), (2, (2, 6), 1, Decimal(22600))],
)
def test_phase2_v2_occupancy_quotes_have_per_room_and_child_evidence(
    adults: int, children: tuple[int, ...], rooms: int, total: Decimal
) -> None:
    async def check() -> None:
        world = phase2_world()
        city = world.cities[0]
        point = GeoPoint(name=city.city, latitude=city.latitude, longitude=city.longitude)
        request = TravelRequest(
            city=city.city,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 12),
            adults=adults,
            child_ages=children,
            rooms=rooms,
            revision=1,
        )
        transport = fault_transport(
            "phase2-world",
            profile="eval",
            database_dsn=f"postgresql://localhost/travel_agent_eval_{'a' * 32}",
            world=world,
        )
        async with httpx.AsyncClient(transport=transport) as http:
            provider = Rakuten(
                "test", "test", "", "", http, _CountingUsage({}), data_mode="synthetic"
            )
            offers = await provider.search(request, point, limit=5)
        assert offers and all(offer.total is not None for offer in offers)
        assert offers[0].total == total
        if children:
            assert len(offers) == 4
            assert all(
                "家庭房" in room_assessment(offer.room_type, request).room_tags for offer in offers
            )

    asyncio.run(check())


@pytest.mark.parametrize("fault", ["empty", "429-ok", "timeout-ok"])
def test_phase2_v2_faults_stay_on_local_transport_then_recover(
    fault: str,
) -> None:
    world = phase2_world()
    transport = fault_transport(
        fault,
        profile="eval",
        database_dsn=f"postgresql://localhost/travel_agent_eval_{'a' * 32}",
        world=world,
    )
    city = world.cities[0]
    place_request = httpx.Request(
        "POST",
        "https://places.googleapis.com/v1/places:searchText",
        json={"textQuery": f"博物馆 {city.city}", "pageSize": 8},
    )
    hotel_request = httpx.Request(
        "GET",
        "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426",
        params={
            "latitude": city.latitude,
            "longitude": city.longitude,
            "checkinDate": "2026-11-10",
            "adultNum": 2,
        },
    )
    with httpx.Client(transport=transport) as http:
        if fault == "empty":
            assert http.send(place_request).json() == {"places": []}
            assert http.send(hotel_request).status_code == 404
            return
        for request in (place_request, hotel_request):
            if fault == "timeout-ok":
                with pytest.raises(httpx.ReadTimeout):
                    http.send(request)
            else:
                assert http.send(request).status_code == 429
            result = http.send(request)
            assert result.status_code == 200
            assert result.json()["places" if request is place_request else "hotels"]


def test_phase2_rakuten_projection_keeps_private_snapshot_quote_semantics() -> None:
    frozen, commission = load_world()
    original = frozen.hotels[0]
    sample = original.model_copy(
        update={
            "prices_jpy": {
                "weekday": (7000, 12000),
                "weekend": (9000, 15000),
                "event": (12000, None),
            },
            "breakfast_by_demand": {
                "weekday": (True, False),
                "weekend": (False, True),
                "event": (False, None),
            },
        }
    )
    stand_in = World(
        source="rakuten", stations=frozen.stations, hotels=(sample, *frozen.hotels[1:])
    )
    world = phase2_world((stand_in, commission))
    assert not world.synthetic_calendar and not world.weather_by_date
    city = world.cities[0]
    first = city.hotels[0]
    assert (first.latitude, first.longitude) == (original.latitude, original.longitude)
    assert first.partner == commission[sample.hotel_id].partner

    for adults, price, breakfast in ((1, 7000, 1), (2, 12000, 0)):
        offers, count = search(world, city, "2026-11-10", adults)
        assert len(offers) == count == 16
        offer = offers[0]
        assert offer.charge and offer.charge.rakutenCharge == price
        assert offer.room.withBreakfastFlag == breakfast
        assert offer.room.roomName == "禁煙ツイン個室"
        assert offer.room.evaluationMaxGuests is None and not offer.charge.evaluationFixedPerRoom
    event, count = search(world, city, "2026-11-23", 2)
    assert len(event) == count == 15
    assert all(offer.hotel.hotelNo != first.number for offer in event)
    assert search(world, city, "2026-11-10", 3) == ((), 0)

"""六城供应商夹具契约。请求均由 MockTransport 处理。"""

from datetime import date
from typing import Any

import httpx

from backend.adapters.evaluation_faults import fault_transport
from backend.adapters.evaluation_world import places, serve
from eval.core.evaluation_world import phase2_world

NAMED = {
    "京都": ("桂離宮", "清水寺"),
    "東京": ("三鷹の森ジブリ美術館", "上野動物園"),
    "大阪": ("海遊館", "大阪城"),
    "奈良": ("東大寺", "奈良公園"),
    "札幌": ("大通公園", "白い恋人パーク"),
    "福岡": ("太宰府天満宮", "大濠公園"),
}


def test_six_city_catalog_is_deterministic_and_distinguishes_text_queries() -> None:
    world = phase2_world()
    assert world.model_dump_json() == phase2_world().model_dump_json()
    for city in world.cities:
        catalog: Any = places(city)
        assert len(catalog) >= 24
        categories = {row["types"][0] for row in catalog}
        assert categories >= {
            "museum",
            "art_gallery",
            "park",
            "garden",
            "aquarium",
            "zoo",
            "viewpoint",
            "shopping_mall",
            "shrine",
            "temple",
            "national_park",
            "restaurant",
            "cafe",
        }
        assert sum(row["types"][0] in {"restaurant", "cafe"} for row in catalog) >= 4
        assert {row["evaluationIndoor"] for row in catalog} == {False, True}
        periods = [row["regularOpeningHours"]["periods"] for row in catalog]
        assert any({p["open"]["day"] for p in schedule} != set(range(7)) for schedule in periods)
        assert any(
            p["close"]["hour"] * 60 + p["close"]["minute"] < 16 * 60 + 30
            for schedule in periods
            for p in schedule
        )
        found: list[set[str]] = []
        for text in ("博物馆", "公园", "餐厅"):
            query = httpx.Request(
                "POST",
                "https://places.googleapis.com/v1/places:searchText",
                json={"textQuery": f"{text} {city.city}", "pageSize": 8},
            )
            first, second = serve(query, world), serve(query, world)
            assert first is not None and second is not None
            assert first.content == second.content
            ids = {row["id"] for row in first.json()["places"]}
            assert ids and all(ids.isdisjoint(previous) for previous in found)
            found.append(ids)
        for name in NAMED[city.city]:
            result = serve(
                httpx.Request(
                    "POST",
                    "https://places.googleapis.com/v1/places:searchText",
                    json={"textQuery": f"{name} {city.city}", "pageSize": 1},
                ),
                world,
            )
            assert result is not None
            assert result.json()["places"][0]["displayName"]["text"] == name


def test_phase2_walking_routes_reflect_relative_distance() -> None:
    world = phase2_world()

    def seconds(delta: float) -> int:
        response = serve(
            httpx.Request(
                "POST",
                "https://routes.googleapis.com/directions/v2:computeRoutes",
                json={
                    "origin": {"location": {"latLng": {"latitude": 35.0, "longitude": 135.0}}},
                    "destination": {
                        "location": {"latLng": {"latitude": 35.0 + delta, "longitude": 135.0}}
                    },
                    "travelMode": "WALK",
                },
            ),
            world,
        )
        assert response is not None
        return int(response.json()["routes"][0]["duration"].removesuffix("s"))

    assert 0 < seconds(0.001) < seconds(0.02)


def test_phase2_weather_can_select_rain_and_sun_on_consecutive_days() -> None:
    world = phase2_world(weather_by_date={date(2026, 11, 3): "rain", date(2026, 11, 4): "sunny"})
    transport = fault_transport(
        "phase2-world",
        profile="eval",
        database_dsn=f"postgresql://localhost/travel_agent_eval_{'a' * 32}",
        world=world,
    )
    with httpx.Client(transport=transport) as client:
        response = client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "start_date": "2026-11-03",
                "end_date": "2026-11-04",
                "latitude": 35,
            },
        )
    assert response.json()["daily"]["precipitation_probability_max"] == [85, 10]
    assert response.json()["daily"]["weather_code"] == [61, 0]

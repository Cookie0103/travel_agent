"""故障transport须专用评测库与显式eval用途；生产无开关。"""

from uuid import uuid4

import httpx
import pytest

from backend.adapters.evaluation_faults import fault_transport


@pytest.mark.parametrize(
    "profile,dsn",
    [
        ("default", "postgresql://localhost/travel_agent"),
        ("eval", "postgresql://example.com/travel_agent_eval_" + "a" * 32),
        ("eval", "postgresql://localhost/travel_agent"),
    ],
)
def test_fault_injection_cannot_be_enabled_in_production(profile: str, dsn: str) -> None:
    with pytest.raises(ValueError):
        fault_transport("429-ok", profile=profile, database_dsn=dsn)


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("429-ok", [429, 200]),
        ("429-twice", [429, 429]),
        ("400", [400, 400]),
        ("empty", [404, 404]),
        ("coverage", [200, 200]),
        ("budget-double", [200, 200]),
        ("budget-none", [200, 200]),
    ],
)
def test_injected_sequences_are_closed_and_never_network(
    scenario: str, expected: list[int]
) -> None:
    transport = fault_transport(
        scenario,
        profile="eval",
        database_dsn="postgresql://localhost/travel_agent_eval_" + uuid4().hex,
    )
    with httpx.Client(transport=transport) as client:
        assert [
            client.get(
                "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426",
                params={"checkinDate": "2026-11-03"},
            ).status_code
            for _ in range(2)
        ] == expected


def test_three_city_place_inventory_is_distinct_complete_and_stable_on_detail_read() -> None:
    transport = fault_transport(
        "coverage",
        profile="eval",
        database_dsn="postgresql://localhost/travel_agent_eval_" + uuid4().hex,
    )
    ids: set[str] = set()
    coordinates: set[tuple[float, float]] = set()
    with httpx.Client(transport=transport) as client:
        for city in ("京都", "大阪", "奈良"):
            places = client.post(
                "https://places.googleapis.com/v1/places:searchText",
                json={"textQuery": "観光スポット " + city, "pageSize": 20},
            ).json()["places"]
            assert len(places) >= 12
            city_ids = {p["id"] for p in places}
            city_coordinates = {
                (p["location"]["latitude"], p["location"]["longitude"]) for p in places
            }
            assert not ids & city_ids and not coordinates & city_coordinates
            assert all(p["displayName"]["text"].startswith("合成" + city) for p in places)
            detail = client.get(
                "https://places.googleapis.com/v1/places/" + places[-1]["id"]
            ).json()
            assert detail == places[-1]
            ids.update(city_ids)
            coordinates.update(city_coordinates)
        assert (
            client.get(
                "https://places.googleapis.com/v1/places/synthetic-京都-place-999"
            ).status_code
            == 404
        )

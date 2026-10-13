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

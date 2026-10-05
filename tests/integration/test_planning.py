"""R06：真实PostgreSQL证据下的路线/校验工具，归属与版本错误不能降级为通过。"""

import asyncio
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from backend.domain.evidence import EvidenceRecord
from backend.domain.execution import RunContext
from backend.domain.itinerary import ItineraryProposal, ProposedItem
from backend.domain.travel_request import RequestPatch
from backend.persistence.catalog import import_catalog
from backend.services.catalog import CatalogService
from backend.services.common import transaction
from backend.services.travel import TravelService
from backend.tools.travel import TravelToolExecutor
from data.import_catalog import load_snapshot
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


async def destinations(
    travel: TravelService, context: RunContext
) -> tuple[EvidenceRecord, EvidenceRecord]:
    async with transaction(travel.database) as db:
        await import_catalog(db, load_snapshot())
    catalog = CatalogService(travel)
    first = await catalog.get(context, "places", "osm:way/57111281")
    second = await catalog.get(context, "places", "osm:way/314446153")
    return first.evidence[0], second.evidence[0]


def proposal(evidence: EvidenceRecord, *, closed: bool = False) -> ItineraryProposal:
    return ItineraryProposal(
        expected_revision=evidence.request_revision,
        items=(
            ProposedItem(
                place_evidence_id=evidence.evidence_id,
                start=datetime.fromisoformat(
                    "2026-11-03T18:00+09:00" if closed else "2026-11-03T10:00+09:00"
                ),
                end=datetime.fromisoformat(
                    "2026-11-03T19:00+09:00" if closed else "2026-11-03T11:00+09:00"
                ),
            ),
        ),
    )


def test_routes_require_confirmed_transport_and_publish_current_party_estimates(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    executor = TravelToolExecutor(travel)

    async def exercise() -> None:
        first, second = await destinations(travel, context)
        args = {
            "expected_revision": 1,
            "legs": [
                {
                    "from_evidence_id": str(first.evidence_id),
                    "to_evidence_id": str(second.evidence_id),
                    "departure": "2026-11-03T11:00+09:00",
                }
            ],
        }
        missing = await executor.execute(context, "estimate_routes", args)
        assert missing.code == "validation" and "transport" in missing.suggestion
        await travel.patch_request(
            context,
            RequestPatch.model_validate({"expected_revision": 1, "set": {"transport": "transit"}}),
        )
        first, second = await destinations(travel, context)
        args = {
            "expected_revision": 2,
            "legs": [
                {
                    "from_evidence_id": str(first.evidence_id),
                    "to_evidence_id": str(second.evidence_id),
                    "departure": "2026-11-03T11:00+09:00",
                }
            ],
        }
        result = await executor.execute(context, "estimate_routes", args)
        assert result.code is None and result.data_mode == "fixture"
        routes = result.data["routes"]
        assert (
            isinstance(routes, list)
            and routes[0]["fare"] == "460"
            and routes[0]["confidence"] == "estimate"
        )
        resolved = await travel.resolve_evidence(context, (UUID(result.evidence_ids[0]),))
        assert resolved[0].kind == "route" and resolved[0].request_revision == 2
        legs = args["legs"]
        assert isinstance(legs, list)
        forged = await executor.execute(
            context,
            "estimate_routes",
            {**args, "legs": [{**legs[0], "from_evidence_id": str(uuid4())}]},
        )
        assert forged.code == "blocked" and not forged.data
        wrong_user = TravelToolExecutor(travel)
        other = await wrong_user.execute(
            RunContext(uuid4(), context.session_id),
            "validate_itinerary",
            proposal(first).model_dump(mode="json"),
        )
        assert other.code == "blocked"
        await travel.patch_request(
            context, RequestPatch.model_validate({"expected_revision": 2, "set": {"rooms": 2}})
        )
        stale = await executor.execute(
            context, "validate_itinerary", proposal(first).model_dump(mode="json")
        )
        assert stale.code == "conflict" and not stale.data

    runner.run(exercise())


def test_validator_feedback_limit_and_schema_cannot_be_overridden(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    executor = TravelToolExecutor(travel)

    async def exercise() -> None:
        first, _ = await destinations(travel, context)
        args = proposal(first, closed=True).model_dump(mode="json")
        injected = await executor.execute(
            context, "validate_itinerary", {**args, "status": "complete"}
        )
        assert injected.code == "validation"
        for remaining in (3, 2, 1, 0):
            result = await executor.execute(context, "validate_itinerary", args)
            assert result.code is None and result.data["status"] == "conflict"
            assert result.data["repair_rounds_remaining"] == remaining
        blocked = await executor.execute(
            context, "validate_itinerary", proposal(first).model_dump(mode="json")
        )
        assert blocked.code == "blocked" and not blocked.data
        assert (
            await TravelToolExecutor(travel).execute(
                context, "validate_itinerary", proposal(first).model_dump(mode="json")
            )
        ).data["status"] == "partial"

    runner.run(exercise())


def test_route_source_unavailable_returns_safe_error(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await travel.patch_request(
            context,
            RequestPatch.model_validate({"expected_revision": 1, "set": {"transport": "walk"}}),
        )
        first, second = await destinations(travel, context)

        def unavailable() -> None:
            raise OSError("private filename")

        monkeypatch.setattr("backend.services.planning.load_routes", unavailable)
        result = await TravelToolExecutor(travel).execute(
            context,
            "estimate_routes",
            {
                "expected_revision": 2,
                "legs": [
                    {
                        "from_evidence_id": str(first.evidence_id),
                        "to_evidence_id": str(second.evidence_id),
                        "departure": "2026-11-03T11:00+09:00",
                    }
                ],
            },
        )
        assert result.code == "unavailable" and "private" not in result.suggestion

    runner.run(exercise())

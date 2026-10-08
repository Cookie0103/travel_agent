"""真实PG持久化展示侧列；旧报价/正式版本不增加新字段。"""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.domain.execution import RunContext
from backend.domain.hotel_details import HotelDisplayDetails
from backend.domain.hotels import HotelOffer
from backend.domain.plans import StageInput
from backend.persistence.models import EvidenceRow, PlanVersionRow
from backend.services.common import transaction
from backend.services.hotels import HotelService
from backend.services.plans import PlanService
from backend.services.travel import TravelService
from tests.fixtures.legacy_hotel_display_v1 import HotelDisplayDetails as LegacyDetails
from tests.fixtures.legacy_hotel_offer_v1 import HotelOffer as LegacyOffer
from tests.integration.test_planning import destinations, proposal
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration
METADATA = {
    "address": "京都府京都市合成町1",
    "latitude": 34.9851,
    "longitude": 135.7587,
    "review_count": 0,
}


def test_metadata_survives_reopen_and_formal_version_without_quote_changes(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        original = (await HotelService(travel).search(context, 1, limit=1))[0]
        record = original.model_copy(
            update={
                "evidence_id": uuid4(),
                "display_details": HotelDisplayDetails.model_validate(METADATA),
            }
        )
        await travel.record_evidence(context, (record,))
        async with transaction(travel.database) as db:
            row = await db.get(EvidenceRow, record.evidence_id)
            assert row and row.payload == original.model_dump(mode="json") | {
                "evidence_id": str(record.evidence_id),
            }
            assert row.display_details
            assert LegacyDetails.model_validate(row.display_details).model_dump() == {
                "hotel_info_url": None,
                "plan_list_url": None,
                "reservation_url": None,
            }
            assert row.hotel_metadata == METADATA
            LegacyOffer.model_validate(row.payload["value"])
            row.payload = {**row.payload, "content_version": "old-writer"}
        target = travel.database.engine.url
        assert target.host in {"127.0.0.1", "localhost"}
        assert target.database and target.database.startswith("travel_agent_test_")
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine

        from backend.persistence.database import ROOT

        engine = create_engine(target, hide_parameters=True)
        try:
            with engine.begin() as connection:
                config = Config(str(ROOT / "backend/persistence/alembic.ini"))
                config.attributes["connection"] = connection
                command.downgrade(config, "0014")
                command.upgrade(config, "head")
                command.check(config)
        finally:
            engine.dispose()
        reopened = TravelService(travel.database)
        resolved = (await reopened.resolve_evidence(context, (record.evidence_id,)))[0]
        assert resolved.content_version == "old-writer"
        assert resolved.display_details
        assert {key: resolved.display_details.model_dump()[key] for key in METADATA} == METADATA
        current = await HotelService(reopened).present(context, 1, (record.evidence_id,))
        cards = current["cards"]
        assert isinstance(cards, list) and isinstance(cards[0], dict)
        assert {key: cards[0][key] for key in METADATA} == METADATA
        assert cards[0]["total"] == str(HotelOffer.model_validate(record.value).total)
        first, _ = await destinations(travel, context)
        candidate = proposal(first).model_copy(update={"hotel_evidence_id": record.evidence_id})
        service = PlanService(travel)
        draft = await service.stage(
            context,
            StageInput.model_validate(
                {
                    "change": {"kind": "initial", "proposal": candidate.model_dump(mode="json")},
                }
            ),
        )
        saved = await service.confirm(context.user_id, draft.draft_id)
        async with transaction(travel.database) as db:
            before = (
                (
                    await db.scalars(
                        select(PlanVersionRow).where(PlanVersionRow.plan_id == saved.plan_id)
                    )
                )
                .one()
                .payload
            )
        view = await PlanService(reopened).get(context.user_id, saved.plan_id)
        hotel = view["hotel"]
        assert isinstance(hotel, dict) and {key: hotel[key] for key in METADATA} == METADATA
        assert view["version"] == 1
        async with transaction(travel.database) as db:
            after = (
                (
                    await db.scalars(
                        select(PlanVersionRow).where(PlanVersionRow.plan_id == saved.plan_id)
                    )
                )
                .one()
                .payload
            )
        assert before == after
        old = (await HotelService(reopened).present(context, 1, (original.evidence_id,)))["cards"]
        assert isinstance(old, list) and isinstance(old[0], dict)
        assert all(old[0][key] is None for key in METADATA)

    runner.run(exercise())

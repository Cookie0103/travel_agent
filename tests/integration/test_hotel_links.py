"""本地PG保存链接侧列、旧报价/预订形状与回退后读回；不请求供应商API。"""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.domain.booking import HoldHotelInput
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution import RunContext
from backend.domain.hotels import HotelOffer
from backend.persistence.models import BookingRow, EvidenceRow, SupplierHoldRow, SupplierOrderRow
from backend.services.bookings import BookingService
from backend.services.common import ServiceError, transaction
from backend.services.hotels import HotelService
from backend.services.travel import TravelService
from mock_supplier.service import SupplierService
from tests.fixtures.legacy_hotel_offer_v1 import HotelOffer as LegacyOffer
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_hotel_links import URLS

pytestmark = pytest.mark.integration


async def stored_link_quote(travel: TravelService, context: RunContext) -> EvidenceRecord:
    original = (await HotelService(travel).search(context, 1, limit=1))[0]
    quote = HotelOffer.model_validate(original.value)
    live = quote.model_copy(update={"data_mode": "live", "included_total": quote.total})
    record = EvidenceRecord.model_validate(
        {
            **original.model_dump(mode="json"),
            "evidence_id": str(uuid4()),
            "entity_id": str(live.offer_id),
            "value": live.model_dump(mode="json"),
            "data_mode": "live",
            "provider": "rakuten_travel",
            "source_ref": URLS["hotel_info_url"],
            "display_details": URLS,
        }
    )
    await travel.record_evidence(context, (record,))
    async with transaction(travel.database) as db:
        row = await db.get(EvidenceRow, record.evidence_id)
        assert row and row.display_details == URLS
        assert "display_details" not in row.payload
        restored = LegacyOffer.model_validate(row.payload["value"])
        assert restored.offer_id == live.offer_id
        # 旧写入者更新旧payload，不能删除细节；新元数据不混入报价事实。
        row.payload = {**row.payload, "content_version": "old-writer"}
    return record


def test_link_sidecar_survives_reopen_old_writer_and_rollback(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    record = runner.run(stored_link_quote(travel, context))
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
            command.downgrade(config, "0013")
            command.upgrade(config, "head")
            command.check(config)
    finally:
        engine.dispose()

    async def read() -> None:
        reopened = TravelService(travel.database)
        hotels = HotelService(reopened)
        known = (await hotels.known_quotes(context, (record.evidence_id,)))[0]
        resolved = (await reopened.resolve_evidence(context, (record.evidence_id,)))[0]
        assert known.display_details == resolved.display_details
        assert known.display_details and known.display_details.model_dump() == URLS
        assert known.content_version == "old-writer"
        presentation = await hotels.present(context, 1, (record.evidence_id,))
        cards = presentation["cards"]
        assert isinstance(cards, list) and isinstance(cards[0], dict)
        assert {key: cards[0][key] for key in URLS} == URLS
        with pytest.raises(ServiceError) as failed:
            await BookingService(reopened).hold(
                context,
                HoldHotelInput(
                    expected_revision=1,
                    offer_id=HotelOffer.model_validate(record.value).offer_id,
                ),
            )
        assert failed.value.status == 422 and failed.value.code == "blocked"
        assert "实时酒店" in str(failed.value)
        old = (await hotels.search(context, 1, limit=1))[0]
        old_card = (await hotels.present(context, 1, (old.evidence_id,)))["cards"]
        assert isinstance(old_card, list) and isinstance(old_card[0], dict)
        assert all(old_card[0][key] is None for key in URLS)

    runner.run(read())


def test_fixture_booking_and_supplier_snapshots_stay_legacy_readable(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        record = (await HotelService(travel).search(context, 1, limit=1))[0]
        quote = HotelOffer.model_validate(record.value)
        assert quote.display_details is None and record.display_details is None
        service = BookingService(travel, SupplierService(travel.database))
        body = HoldHotelInput(offer_id=quote.offer_id, expected_revision=1)
        held = await service.hold(context, body)
        assert held.status == "held"
        assert (await service.hold(context, body)).booking_id == held.booking_id
        async with transaction(travel.database) as db:
            booking = await db.get(BookingRow, held.booking_id)
            supplier = await db.get(SupplierHoldRow, held.client_ref)
            assert booking and supplier
            for payload in (booking.payload, supplier.payload):
                old = LegacyOffer.model_validate(payload["offer"])
                assert old.offer_id == quote.offer_id
            assert not list(
                await db.scalars(
                    select(SupplierOrderRow).where(
                        SupplierOrderRow.client_ref == held.client_ref,
                    )
                )
            )
        assert (await BookingService(travel).get(context.user_id, held.booking_id)).offer == quote

    runner.run(exercise())


def test_formal_plan_reopen_preserves_link_sidecar_without_changing_saved_content(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    from backend.domain.plans import StageInput
    from backend.persistence.models import PlanVersionRow
    from backend.services.plans import PlanService
    from tests.integration.test_planning import destinations, proposal

    runner, travel, context = travel_setup

    async def exercise() -> None:
        record = await stored_link_quote(travel, context)
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
        view = await PlanService(TravelService(travel.database)).get(context.user_id, saved.plan_id)
        hotel = view["hotel"]
        assert isinstance(hotel, dict) and {key: hotel[key] for key in URLS} == URLS
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
        assert after == before
        assert saved.content.hotel_evidence_id == record.evidence_id

    runner.run(exercise())

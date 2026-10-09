"""R05：真实数据库中的报价归属、有效期、条件变化和服务端卡片补全。"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from backend.domain.execution import RunContext
from backend.domain.hotels import HotelOffer
from backend.domain.travel_request import RequestPatch
from backend.persistence.models import EvidenceRow
from backend.services.common import ServiceError, transaction
from backend.services.hotels import HotelService
from backend.services.travel import TravelService
from backend.tools.travel import TravelToolExecutor
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def test_tools_return_six_cards_and_comparison_cannot_accept_model_prices(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    executor = TravelToolExecutor(travel)

    async def exercise() -> None:
        result = await executor.execute(
            context, "search_hotel_offers", {"expected_revision": 1, "limit": 6}
        )
        assert result.code is None and result.data_mode == "fixture"
        offers = result.data["offers"]
        assert isinstance(offers, list) and len(offers) == 6
        arguments = {
            "component": "hotel_comparison",
            "expected_revision": 1,
            "offer_ids": [o["offer_id"] for o in offers],
        }
        presented = await executor.execute(context, "present_travel_result", arguments)
        assert presented.code is None
        assert presented.evidence_ids == result.evidence_ids
        comparison = presented.data["comparison"]
        assert isinstance(comparison, dict) and comparison["comparable"] is False
        assert comparison["lowest_offer_ids"] == []
        forged_price = await executor.execute(
            context, "present_travel_result", {**arguments, "total": "1"}
        )
        assert forged_price.code == "validation"
        assert (
            "hotel_comparison" in forged_price.suggestion and "itinerary" in forged_price.suggestion
        )
        duplicate = await executor.execute(
            context,
            "present_travel_result",
            {**arguments, "offer_ids": [offers[0]["offer_id"], offers[0]["offer_id"]]},
        )
        assert duplicate.code == "validation"
        forged_id = await executor.execute(
            context,
            "present_travel_result",
            {**arguments, "offer_ids": [offers[0]["offer_id"], str(uuid4())]},
        )
        assert forged_id.code == "blocked" and not forged_id.data
        valid = await executor.execute(
            context,
            "present_travel_result",
            {**arguments, "offer_ids": [offers[0]["offer_id"], offers[1]["offer_id"]]},
        )
        comparison = valid.data["comparison"]
        assert isinstance(comparison, dict) and comparison["lowest_offer_ids"] == [
            offers[0]["offer_id"]
        ]

    runner.run(exercise())


def test_request_change_rejects_old_cards_and_refresh_uses_new_conditions(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    hotels = HotelService(travel)

    async def exercise() -> None:
        records = await hotels.search(context, 1, limit=1)
        old = HotelOffer.model_validate(records[0].value)
        await travel.patch_request(
            context, RequestPatch.model_validate({"expected_revision": 1, "set": {"rooms": 2}})
        )
        with pytest.raises(ServiceError, match="已失效"):
            await hotels.present(context, 2, (old.offer_id,))
        new_records = await hotels.refresh(context, 2, old.offer_id)
        new = HotelOffer.model_validate(new_records[0].value)
        assert new.offer_id != old.offer_id and new.request.rooms == 2 and new.request.revision == 2
        assert old.total is not None
        assert new.total == old.total * 2
        with pytest.raises(ServiceError, match="不属于"):
            await hotels.refresh(RunContext(uuid4(), context.session_id), 2, old.offer_id)

    runner.run(exercise())


def test_expired_quote_is_readable_only_as_refresh_locator(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    hotels = HotelService(travel)

    async def exercise() -> None:
        record = (await hotels.search(context, 1, limit=1))[0]
        now = datetime.now(UTC)
        old = HotelOffer.model_validate(record.value).model_copy(
            update={
                "quoted_at": now - timedelta(minutes=10),
                "expires_at": now - timedelta(minutes=5),
            }
        )
        stale = record.model_copy(
            update={
                "value": old.model_dump(mode="json"),
                "retrieved_at": old.quoted_at,
                "valid_until": old.expires_at,
            }
        )
        async with transaction(travel.database) as db:
            row = await db.get(EvidenceRow, record.evidence_id)
            assert row is not None
            row.payload = stale.model_dump(mode="json")
        with pytest.raises(ServiceError, match="已失效"):
            await hotels.present(context, 1, (old.offer_id,))
        refreshed = await hotels.refresh(context, 1, old.offer_id)
        assert UUID(refreshed[0].entity_id) != old.offer_id and refreshed[0].valid_until > now

    runner.run(exercise())


def test_missing_children_empty_results_and_unavailable_are_distinct(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, travel, context = travel_setup
    executor = TravelToolExecutor(travel)

    async def exercise() -> None:
        result = await executor.execute(
            context, "search_hotel_offers", {"expected_revision": 1, "hotel_id": "absent"}
        )
        assert result.empty and result.code is None
        await travel.patch_request(
            context, RequestPatch.model_validate({"expected_revision": 1, "clear": ["child_ages"]})
        )
        missing = await executor.execute(context, "search_hotel_offers", {"expected_revision": 2})
        assert missing.code == "validation" and "child_ages" in missing.suggestion
        await travel.patch_request(
            context,
            RequestPatch.model_validate({"expected_revision": 2, "set": {"child_ages": []}}),
        )

        def unavailable() -> None:
            raise OSError("private fixture path must not leak")

        monkeypatch.setattr("backend.services.hotels.load_rates", unavailable)
        failed = await executor.execute(context, "search_hotel_offers", {"expected_revision": 3})
        assert failed.code == "unavailable" and "private" not in failed.suggestion

    runner.run(exercise())


def test_search_four_hotels_keeps_unique_hotel_coverage_and_two_rates(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.providers.hotel_fixture import load_rates

    rates, version = load_rates()
    grouped = tuple(sorted(rates, key=lambda rate: rate.hotel_id))
    monkeypatch.setattr("backend.services.hotels.load_rates", lambda: (grouped, version))
    runner, travel, context = travel_setup

    async def exercise() -> None:
        records = await HotelService(travel).search(context, 1, limit=4)
        offers = [HotelOffer.model_validate(record.value) for record in records]
        ids = [offer.hotel_id for offer in offers]
        assert len(set(ids)) == 4 and len(offers) == 6
        assert max(ids.count(id) for id in ids) == 2
        presented = await HotelService(travel).present(
            context, 1, tuple(offer.offer_id for offer in offers)
        )
        cards = presented["cards"]
        assert isinstance(cards, list) and len(cards) == 6
        assert [card["offer_id"] for card in cards] == [str(offer.offer_id) for offer in offers]

    runner.run(exercise())

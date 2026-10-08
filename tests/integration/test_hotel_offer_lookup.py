"""酒店报价ID查找：复现生产 offer_not_found 的各候选原因（本地PG，无网络）。"""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from backend.domain.execution import RunContext
from backend.domain.travel_request import RequestPatch
from backend.services.common import ServiceError
from backend.services.hotels import HotelService
from backend.tools.travel import TravelToolExecutor
from tests.integration.test_planning import destinations
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def present(revision: int, ids: list[str]) -> dict[str, object]:
    return {"component": "hotel_comparison", "expected_revision": revision, "offer_ids": ids}


async def search(
    executor: TravelToolExecutor, context: RunContext, revision: int
) -> list[dict[str, object]]:
    result = await executor.execute(
        context, "search_hotel_offers", {"expected_revision": revision, "limit": 2}
    )
    assert result.code is None
    offers = result.data["offers"]
    assert isinstance(offers, list) and len(offers) == 2
    return offers


def test_present_accepts_search_offer_ids_and_the_card_evidence_ids(
    travel_setup: tuple[asyncio.Runner, object, RunContext],
) -> None:
    runner, travel, context = travel_setup
    executor = TravelToolExecutor(travel)  # type: ignore[arg-type]

    async def exercise() -> None:
        offers = await search(executor, context, 1)
        by_offer = await executor.execute(
            context, "present_travel_result", present(1, [str(o["offer_id"]) for o in offers])
        )
        assert by_offer.code is None, by_offer.detail
        # 模型把卡片里的 evidence_id 当 offer_id 传入也应能呈现（生产 404 的最可能原因）。
        by_evidence = await executor.execute(
            context, "present_travel_result", present(1, [str(o["evidence_id"]) for o in offers])
        )
        assert by_evidence.code is None, by_evidence.detail

    runner.run(exercise())


def test_second_run_in_same_session_still_finds_first_run_offers(
    travel_setup: tuple[asyncio.Runner, object, RunContext],
) -> None:
    runner, travel, context = travel_setup
    executor = TravelToolExecutor(travel)  # type: ignore[arg-type]

    async def exercise() -> None:
        offers = await search(executor, context, 1)
        later = replace(context, run_id=uuid4())
        ids = [str(o["offer_id"]) for o in offers]
        result = await TravelToolExecutor(travel).execute(  # type: ignore[arg-type]
            later, "present_travel_result", present(1, ids)
        )
        assert result.code is None, result.detail

    runner.run(exercise())


def test_unrelated_edit_keeps_offers_but_stay_change_stales_them_with_kind_and_remedy(
    travel_setup: tuple[asyncio.Runner, object, RunContext],
) -> None:
    runner, travel, context = travel_setup
    executor = TravelToolExecutor(travel)  # type: ignore[arg-type]

    async def exercise() -> None:
        offers = await search(executor, context, 1)
        ids = [str(o["offer_id"]) for o in offers]
        budget = RequestPatch.model_validate({"expected_revision": 1, "set": {"budget": "90000"}})
        await travel.patch_request(context, budget)  # type: ignore[attr-defined]
        old = await executor.execute(context, "present_travel_result", present(1, ids))
        assert old.code == "conflict", (old.code, old.detail)  # 版本仍需最新
        kept = await executor.execute(context, "present_travel_result", present(2, ids))
        assert kept.code is None, kept.detail  # 预算变化不使仍有效的报价过期
        stay = RequestPatch.model_validate({"expected_revision": 2, "set": {"rooms": 2}})
        await travel.patch_request(context, stay)  # type: ignore[attr-defined]
        stale = await executor.execute(context, "present_travel_result", present(3, ids))
        assert stale.code == "conflict"
        assert stale.detail[-1] == "evidence_stale:hotel_offer"
        assert "search_hotel_offers" in stale.suggestion

    runner.run(exercise())


def test_hotel_evidence_used_as_place_reports_kind_and_static_hint(
    travel_setup: tuple[asyncio.Runner, object, RunContext],
) -> None:
    runner, travel, context = travel_setup
    executor = TravelToolExecutor(travel)  # type: ignore[arg-type]

    async def exercise() -> None:
        offers = await search(executor, context, 1)
        hotel = str(offers[0]["evidence_id"])
        start = datetime(2026, 11, 3, 10, tzinfo=UTC)
        item = {
            "place_evidence_id": hotel,
            "start": start.isoformat(),
            "end": (start + timedelta(hours=1)).isoformat(),
        }
        result = await executor.execute(
            context,
            "validate_itinerary",
            {"expected_revision": 1, "items": [item], "hotel_evidence_id": hotel},
        )
        assert result.code == "validation"
        assert "validator:地点引用必须是place证据:place_ref_kind=hotel_offer" in result.detail
        assert "hotel_evidence_id" in result.suggestion

    runner.run(exercise())


def test_unknown_and_foreign_ids_are_distinguished_in_trace_detail(
    travel_setup: tuple[asyncio.Runner, object, RunContext],
) -> None:
    runner, travel, context = travel_setup
    executor = TravelToolExecutor(travel)  # type: ignore[arg-type]

    async def exercise() -> None:
        offers = await search(executor, context, 1)
        unknown = await executor.execute(
            replace(context), "present_travel_result", present(1, [str(uuid4())])
        )
        assert unknown.code == "blocked" and unknown.detail[-1] == "offer_unknown_id"
        foreign = replace(context, session_id=uuid4())
        with pytest.raises(ServiceError) as caught:
            await HotelService(travel).known_quotes(  # type: ignore[arg-type]
                foreign, (UUID(str(offers[0]["offer_id"])),)
            )
        assert caught.value.status == 404 and caught.value.reason == "offer_other_session"

    runner.run(exercise())


def test_hotel_ref_kind_label_and_hint_and_valid_offer_passes(
    travel_setup: tuple[asyncio.Runner, object, RunContext],
) -> None:
    runner, travel, context = travel_setup
    executor = TravelToolExecutor(travel)  # type: ignore[arg-type]

    async def exercise() -> None:
        offers = await search(executor, context, 1)
        hotel = str(offers[0]["evidence_id"])
        place = str((await destinations(travel, context))[0].evidence_id)  # type: ignore[arg-type]
        start = datetime(2026, 11, 3, 10, tzinfo=UTC)
        item = {
            "place_evidence_id": place,
            "start": start.isoformat(),
            "end": (start + timedelta(hours=1)).isoformat(),
        }
        bad = await executor.execute(
            context,
            "validate_itinerary",
            {"expected_revision": 1, "items": [item], "hotel_evidence_id": place},
        )
        assert bad.code == "validation"
        assert "validator:酒店引用必须是hotel_offer证据:hotel_ref_kind=place" in bad.detail
        assert "不是offer_id" in bad.suggestion
        good = await executor.execute(
            context,
            "validate_itinerary",
            {"expected_revision": 1, "items": [item], "hotel_evidence_id": hotel},
        )
        assert good.code is None, good.detail

    runner.run(exercise())

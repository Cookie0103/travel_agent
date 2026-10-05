"""酒店报价ID查找：复现生产 offer_not_found 的各候选原因（本地PG，无网络）。"""

import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from backend.domain.execution import RunContext
from backend.domain.travel_request import RequestPatch
from backend.services.common import ServiceError
from backend.services.hotels import HotelService
from backend.tools.travel import TravelToolExecutor
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


def test_non_stay_change_bumps_revision_so_old_revision_is_conflict_not_404(
    travel_setup: tuple[asyncio.Runner, object, RunContext],
) -> None:
    runner, travel, context = travel_setup
    executor = TravelToolExecutor(travel)  # type: ignore[arg-type]

    async def exercise() -> None:
        offers = await search(executor, context, 1)
        ids = [str(o["offer_id"]) for o in offers]
        patch = RequestPatch.model_validate(
            {"expected_revision": 1, "set": {"transport": "transit"}}
        )
        await travel.patch_request(context, patch)  # type: ignore[attr-defined]
        old = await executor.execute(context, "present_travel_result", present(1, ids))
        assert old.code == "conflict", (old.code, old.detail)
        new = await executor.execute(context, "present_travel_result", present(2, ids))
        # 报价绑定旧revision，非住宿字段变化也使其过期；需要重新查询。
        assert new.code == "conflict" and "evidence_stale" in new.detail, (new.code, new.detail)

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

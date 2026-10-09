"""房型偏好必须明确；查询前澄清，不损坏旧报价读取。"""

import asyncio

import httpx
import pytest

from backend.adapters.google_maps import GoogleMaps
from backend.adapters.live_data import LiveData
from backend.adapters.rakuten import Rakuten
from backend.agent.demo import demo_command
from backend.agent.fixture_runtime import FixtureRuntime
from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.hotels import HotelOffer, HotelRate
from backend.domain.travel_request import RequestPatch
from backend.providers.hotel_fixture import load_rates
from backend.services.common import ServiceError
from backend.services.hotels import HotelService
from backend.services.travel import TravelService
from backend.services.views import HotelPresentation
from backend.tools.travel import TravelToolExecutor
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_external_data import _CountingUsage

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("prompt", ["房型无要求，双床，推荐酒店", "独立房间，接受宿舍，推荐酒店"])
def test_conflicting_room_expressions_clarify_without_any_search_or_revision_change(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    prompt: str,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        before = await travel.get_request_view(context)
        events: list[RuntimeEvent] = []
        result = await FixtureRuntime(TravelToolExecutor(travel)).execute(
            context, prompt, None, events.append, asyncio.Event()
        )
        assert result.code is None and "确定" in result.text
        assert [event.kind for event in events] == ["text"]
        assert await travel.get_request_view(context) == before

    runner.run(exercise())


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("住宿改为接受宿舍，床型大床", ["不坐飞机", "房型：禁烟", "床型：双床", "住宿：接受宿舍"]),
        ("床型改为大床，住宿接受宿舍", ["不坐飞机", "住宿：独立房间", "房型：禁烟", "床型：大床"]),
    ],
)
def test_explicit_room_group_cannot_authorize_ordinary_mention_of_other_manual_group(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    prompt: str,
    expected: list[str],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {
                        "hard_constraints": [
                            "不坐飞机",
                            "住宿：独立房间",
                            "房型：禁烟",
                            "床型：双床",
                        ]
                    },
                }
            ),
        )
        assert (await travel.get_request_view(context)).field_sources[
            "hard_constraints"
        ] == "user_form"
        events: list[RuntimeEvent] = []
        result = await FixtureRuntime(TravelToolExecutor(travel)).execute(
            context, prompt, None, events.append, asyncio.Event()
        )
        assert result.code is None
        assert (await travel.get_request(context)).hard_constraints == tuple(expected)
        assert "手动房型" in result.text

    runner.run(exercise())


def test_missing_room_preferences_rejects_before_query_then_explicit_no_preference_works(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, travel, context = travel_setup
    calls: list[bool] = []

    def counted() -> tuple[tuple[HotelRate, ...], str]:
        calls.append(True)
        return load_rates()

    monkeypatch.setattr("backend.services.hotels.load_rates", counted)

    async def exercise() -> None:
        update = await travel.patch_request(
            context,
            RequestPatch.model_validate({"expected_revision": 1, "clear": ["hard_constraints"]}),
        )
        with pytest.raises(ServiceError) as blocked:
            await HotelService(travel).search(context, update.request.revision, limit=1)
        assert (
            blocked.value.code == "validation"
            and blocked.value.reason == "hotel_room_preferences_missing"
        )
        assert "房型" in str(blocked.value) and calls == []
        update = await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": update.request.revision,
                    "set": {"hard_constraints": ["住宿：无要求", "房型：无要求", "床型：无要求"]},
                }
            ),
        )
        records = await HotelService(travel).search(context, update.request.revision, limit=1)
        assert len(records) == 2 and calls == [True]
        assert (
            await HotelService(travel).present(
                context, update.request.revision, tuple(record.evidence_id for record in records)
            )
        )["cards"]

    runner.run(exercise())


def test_missing_preferences_block_live_search_and_refresh_before_any_provider_but_old_quotes_read(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        service = HotelService(travel)
        original = (await service.search(context, 1, limit=1))[0]
        update = await travel.patch_request(
            context,
            RequestPatch.model_validate({"expected_revision": 1, "clear": ["hard_constraints"]}),
        )
        restored = await service.present(context, update.request.revision, (original.evidence_id,))
        panel = HotelPresentation.model_validate(restored)
        assert panel.cards and panel.comparison.room_preferences_question
        usage = _CountingUsage({})

        def never(query: httpx.Request) -> httpx.Response:
            pytest.fail("缺偏好不能调用Google或乐天")

        async with httpx.AsyncClient(transport=httpx.MockTransport(never)) as http:
            travel.live = LiveData(
                GoogleMaps("test", http, usage),
                Rakuten("test", "test", "", "", http, usage),
                usage,
                http,
                {},
            )
            for operation in (
                service.search(context, update.request.revision),
                service.refresh(context, update.request.revision, original.evidence_id),
            ):
                with pytest.raises(ServiceError) as blocked:
                    await operation
                assert blocked.value.reason == "hotel_room_preferences_missing"
            assert usage.calls == 0
            travel.live = None

    runner.run(exercise())


def test_qualification_partition_precedes_limit_and_full_cards_keep_original_size_guard(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, travel, context = travel_setup
    base = load_rates()[0][0]
    names = ("女性専用ドミトリー", "普通双床", "カプセル", "男性限定大床", "standard twin")
    rates = tuple(
        base.model_copy(update={"hotel_id": str(i), "rate_id": str(i), "room_type": name})
        for i, name in enumerate(names)
    )
    monkeypatch.setattr(
        "backend.services.hotels.load_rates", lambda: (rates, "explicit-synthetic-room-names")
    )

    async def exercise() -> None:
        update = await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {"hard_constraints": ["住宿：独立房间", "房型：无要求", "床型：无要求"]},
                }
            ),
        )
        service = HotelService(travel)
        picked = await service.search(context, update.request.revision, limit=2)
        assert [HotelOffer.model_validate(record.value).hotel_id for record in picked] == ["1", "4"]
        all_quotes = await service.search(context, update.request.revision, limit=5)
        assert [HotelOffer.model_validate(record.value).hotel_id for record in all_quotes] == [
            "1",
            "4",
            "0",
            "2",
            "3",
        ]
        result = await TravelToolExecutor(travel).execute(
            context,
            "present_travel_result",
            {
                "component": "hotel_comparison",
                "expected_revision": update.request.revision,
                "offer_ids": [record.entity_id for record in all_quotes],
            },
        )
        assert result.code is None
        panel = HotelPresentation.model_validate(result.data)
        assert [card.hotel_id for card in panel.cards] == ["1", "4", "0", "2", "3"]
        assert panel.cards[2].qualification_unknown and panel.cards[2].room_preference_mismatch
        assert panel.cards[3].room_preference_mismatch and not panel.cards[3].qualification_unknown
        assert [card.total for card in panel.cards] == [panel.cards[0].total] * 5

    runner.run(exercise())


def test_offline_demo_asks_before_tools_and_completes_after_answer(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        events: list[RuntimeEvent] = []
        executor = TravelToolExecutor(travel)
        result = await demo_command(
            executor, context, "演示：比较酒店", events.append, asyncio.Event()
        )
        assert result.code is None and any(event.kind == "presentation" for event in events)
        await travel.patch_request(
            context,
            RequestPatch.model_validate({"expected_revision": 1, "clear": ["hard_constraints"]}),
        )
        events.clear()
        result = await demo_command(
            executor, context, "演示：比较酒店", events.append, asyncio.Event()
        )
        assert result.code is None and "房型" in result.text
        assert [event.kind for event in events] == ["text"]

    runner.run(exercise())

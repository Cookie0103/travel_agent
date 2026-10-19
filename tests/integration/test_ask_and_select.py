"""真实PG：合并选择卡先问、酒店先选后规划（单/多城市同一闸门）、聊天选酒店、跳过。离线夹具，无付费调用。"""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from backend.domain.choices import ChoiceCard
from backend.domain.conversation import ConversationStateInput
from backend.domain.evidence import EvidenceRecord, evidence_conditions
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.domain.hotel_details import StoredHotelDetails
from backend.domain.hotels import HotelRate, quote
from backend.domain.itinerary import HotelStay
from backend.domain.travel_request import (
    RequestPatch,
    TravelRequest,
    segment_request,
    trip_segments,
)
from backend.persistence import runs
from backend.persistence.models import ChoiceCardRow
from backend.providers.claude_agent.database_tools import DatabaseTools
from backend.providers.hotel_fixture import load_rates
from backend.services.choices import ChoiceService
from backend.services.common import ServiceError, transaction
from backend.services.hotel_selection import HotelSelectionService
from backend.services.runs import MessageInput, RunService
from backend.services.travel import TravelService
from backend.tools.contracts import ToolResult
from backend.tools.travel import TravelToolExecutor
from tests.integration.test_runs import WaitingRuntime
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("fixed_today")]

Setup = tuple[asyncio.Runner, TravelService, RunContext]


class FreshExecutor:
    """TravelToolExecutor绑定单个run；每次调用换新的，便于同一测试里换run。"""

    def __init__(self, travel: TravelService) -> None:
        self.travel = travel

    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        return await TravelToolExecutor(self.travel).execute(context, name, arguments)


# 合并卡里的行程信息都已知（房型偏好沿用夹具的“无要求”；文字不含数字，不触发旧的时间确认题）。
KNOWN = {
    "transport": "transit",
    "lodging_budget_unlimited": True,
    "hard_constraints": [
        "住宿：无要求",
        "房型：无要求",
        "床型：无要求",
        "第一天抵达：下午",
        "最后一天离开：傍晚",
    ],
    "soft_constraints": ["节奏：标准", "平时起床：早", "晚上结束：晚", "同行：朋友"],
}


@pytest.fixture
def numeric_hotels(monkeypatch: pytest.MonkeyPatch) -> None:
    """夹具酒店号是kyoto-N；乐天酒店号是数字。换成70001..70006，并加一家大阪的70099。"""
    rates, version = load_rates()
    kyoto = tuple(
        r.model_copy(update={"hotel_id": str(70000 + int(r.hotel_id.split("-")[1]))}) for r in rates
    )
    osaka = kyoto[0].model_copy(
        update={
            "city": "大阪",
            "hotel_id": "70099",
            "hotel_name": "大阪夹具酒店",
            "rate_id": "osaka-1",
        }
    )
    monkeypatch.setattr("backend.services.hotels.load_rates", lambda: ((*kyoto, osaka), version))


async def run_of(
    travel: TravelService, context: RunContext, text: str = "合成用户消息"
) -> RunContext:
    async with transaction(travel.database) as db:
        row = await runs.create(
            db, context.user_id, context.session_id, uuid4(), text, "deepseek", user_text=text
        )
        return replace(context, run_id=row.id)


async def finish(travel: TravelService, context: RunContext) -> None:
    async with transaction(travel.database) as db:
        await runs.finish(db, context, RuntimeOutcome(text="合成完成", sdk_session_id="s"))


async def known(travel: TravelService, context: RunContext, **extra: object) -> TravelRequest:
    return (
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": (await travel.read_request(context)).revision,
                    "set": {**KNOWN, **extra},
                }
            ),
        )
    ).request


async def goals(travel: TravelService, run: RunContext, *tasks: str) -> dict[str, object]:
    request = await travel.read_request(run)
    return await travel.update_conversation_state(
        run,
        ConversationStateInput.model_validate(
            {"expected_revision": request.revision, "goals": tasks}
        ),
    )


def choice_card(view: dict[str, object]) -> ChoiceCard:
    choice = view["choice"]
    assert isinstance(choice, dict)
    return ChoiceCard.model_validate(choice)


def submit_message(
    request: TravelRequest, card: ChoiceCard, option: str, **answers: list[str]
) -> MessageInput:
    selection: dict[str, object] = {"choice_id": str(card.choice_id), "option_id": option}
    if answers:
        selection["answers"] = answers
    return MessageInput.model_validate(
        {
            "client_message_id": str(uuid4()),
            "text": "合成点击",
            "expected_revision": request.revision,
            "selection": selection,
        }
    )


# ---------------- 合并选择卡 ----------------


def test_goals_emit_one_combined_card_that_gates_search_and_planning_until_answered(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup
    service = RunService(
        travel.database, runtime_factory=lambda _: WaitingRuntime(RuntimeOutcome(text="x"))
    )

    async def exercise() -> None:
        first = await run_of(travel, context)
        view = await goals(travel, first, "itinerary")
        card = choice_card(view)
        assert card.form and card.form.purpose == "trip_ask"
        assert [g.key for g in card.form.groups] == [
            "pace", "wake", "evening", "arrival", "departure", "companion", "transport",
        ]  # fmt: skip
        request = await travel.read_request(first)
        tools = DatabaseTools(asyncio.get_running_loop(), travel.database)
        for name in ("search_hotel_offers", "estimate_routes", "stage_plan_change"):
            result = await tools.execute(
                first, name, {"expected_revision": request.revision, "limit": 3}
            )
            assert result.code == "validation" and result.detail == ("trip_details_required",)
            assert "choice" not in result.data  # 同一张未答卡不重复展示
        assert tools.executor.calls == 0
        await finish(travel, first)
        submitted = await service.submit(
            context.user_id,
            context.session_id,
            submit_message(
                request,
                card,
                "confirm",
                pace=["intensive"],
                wake_text=["7:30"],
                arrival=["a1500"],
                companion=["couple"],
                transport=["any"],
            ),  # fmt: skip
        )
        after = await travel.read_request(context)
        assert after.transport == "transit" and "节奏：特种兵" in after.hard_constraints
        assert "平时起床：7:30" in after.soft_constraints and "同行：情侣" in after.soft_constraints
        assert not any(t.startswith("最后一天离开") for t in after.hard_constraints)
        active = RunContext(context.user_id, context.session_id, submitted.run_id)
        # 只问一次：未答的组（evening/departure）不会再发第二张卡；搜索放行
        assert await ChoiceService(travel).ensure_trip_ask(active) == (None, False)
        opened = await tools.execute(
            active, "search_hotel_offers", {"expected_revision": after.revision, "limit": 3}
        )
        assert opened.code is None and not opened.empty
        restored = await ChoiceService(travel).get(
            context.user_id, context.session_id, card.choice_id
        )
        assert restored.answered_option_id == "confirm" and restored.form
        by_key = {g.key: g for g in restored.form.groups}
        assert by_key["wake"].text == "7:30" and by_key["pace"].selected == ("intensive",)
        await service.cancel(context.user_id, submitted.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        await service.close()

    runner.run(exercise())


def test_gate_creates_the_card_when_core_conditions_become_complete_later(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        run = await run_of(travel, context)
        request = await travel.read_request(run)
        await travel.patch_request(
            run,
            RequestPatch.model_validate(
                {"expected_revision": request.revision, "clear": ["end_date"]}
            ),
        )
        view = await goals(travel, run, "itinerary")
        assert "choice" not in view  # 核心条件未齐：先在对话里问，不发卡
        request = await travel.read_request(run)
        await travel.patch_request(
            run,
            RequestPatch.model_validate(
                {"expected_revision": request.revision, "set": {"end_date": "2026-11-05"}}
            ),
        )
        tools = DatabaseTools(asyncio.get_running_loop(), travel.database)
        request = await travel.read_request(run)
        result = await tools.execute(
            run, "search_hotel_offers", {"expected_revision": request.revision, "limit": 3}
        )
        assert result.detail == ("trip_details_required",)
        assert choice_card(result.data).form is not None  # 闸门代发，只发一次
        again = await tools.execute(
            run, "search_hotel_offers", {"expected_revision": request.revision, "limit": 3}
        )
        assert "choice" not in again.data

    runner.run(exercise())


def test_unknown_children_still_issue_the_card_whatever_awaiting_field_the_model_chose(
    travel_setup: Setup,
) -> None:
    """真实回归：模型把awaiting_field设成child_ages并在文字里问儿童，旧逻辑因child_ages未知不发卡。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        run = await run_of(travel, context)
        request = await travel.read_request(run)
        await travel.patch_request(
            run,
            RequestPatch.model_validate(
                {"expected_revision": request.revision, "clear": ["child_ages"]}
            ),
        )
        request = await travel.read_request(run)
        assert request.child_ages is None
        view = await travel.update_conversation_state(
            run,
            ConversationStateInput.model_validate(
                {
                    "expected_revision": request.revision,
                    "goals": ["hotel_comparison", "itinerary"],
                    "awaiting_field": "child_ages",
                }
            ),
        )
        card = choice_card(view)
        assert card.form and card.form.groups[0].key == "children"
        assert view["trip_ask_card"] == "issued" and view["awaiting_field"] is None
        assert "已向用户展示" in str(view["message"])
        # 同一会话再记录一次状态：卡仍未答，不重复发，结果如实说“已有待答卡”
        again = await travel.update_conversation_state(
            run,
            ConversationStateInput.model_validate(
                {"expected_revision": request.revision, "awaiting_field": "child_ages"}
            ),
        )
        assert "choice" not in again and again["trip_ask_card"] == "pending"
        await finish(travel, run)
        service = RunService(
            travel.database, runtime_factory=lambda _: WaitingRuntime(RuntimeOutcome(text="x"))
        )
        submitted = await service.submit(
            context.user_id,
            context.session_id,
            submit_message(request, card, "confirm", children_text=["5岁、8岁"]),
        )
        after = await travel.read_request(context)
        assert after.child_ages == (5, 8)
        active = RunContext(context.user_id, context.session_id, submitted.run_id)
        assert await ChoiceService(travel).ensure_trip_ask(active) == (None, False)
        await service.cancel(context.user_id, submitted.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        await service.close()

    runner.run(exercise())


def test_state_result_says_no_card_when_nothing_is_left_to_ask(travel_setup: Setup) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        run = await run_of(travel, context)
        await known(travel, run)
        view = await goals(travel, run, "hotel_comparison")
        assert "choice" not in view and view["trip_ask_card"] == "none"
        assert "没有" in str(view["message"])

    runner.run(exercise())


def test_changed_conditions_reissue_only_the_remaining_groups_and_retire_the_old_card(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        run = await run_of(travel, context)
        card = choice_card(await goals(travel, run, "itinerary"))
        request = await travel.read_request(run)
        await travel.patch_request(
            run,
            RequestPatch.model_validate(
                {
                    "expected_revision": request.revision,
                    "set": {"soft_constraints": ["同行：朋友"], "transport": "walk"},
                }
            ),
        )
        newer, created = await ChoiceService(travel).ensure_trip_ask(run)
        assert created and newer is not None and newer.form
        assert [g.key for g in newer.form.groups] == [
            "pace", "wake", "evening", "arrival", "departure",
        ]  # fmt: skip
        old = await ChoiceService(travel).get(context.user_id, context.session_id, card.choice_id)
        assert old.stale

    runner.run(exercise())


def test_invalid_card_answers_do_not_start_a_run_or_change_conditions(travel_setup: Setup) -> None:
    runner, travel, context = travel_setup
    service = RunService(travel.database)

    async def exercise() -> None:
        run = await run_of(travel, context)
        card = choice_card(await goals(travel, run, "itinerary"))
        await finish(travel, run)
        request = await travel.read_request(context)
        bad_cases = (
            {"wake": ["w0730"], "wake_text": ["7:30"]},
            {"pace_text": ["快"]},
            {"pace": ["warp"]},
            {"nope": ["a"]},
            {"wake_text": ["x" * 41]},
        )
        for answers in bad_cases:
            with pytest.raises((ServiceError, ValueError)):
                await service.submit(
                    context.user_id,
                    context.session_id,
                    submit_message(request, card, "confirm", **answers),
                )
        assert await travel.read_request(context) == request
        await service.close()

    runner.run(exercise())


# ---------------- 单城市：先选酒店再规划 ----------------


async def shown_hotels(travel: TravelService, run: RunContext) -> list[dict[str, object]]:
    request = await travel.read_request(run)
    executor = FreshExecutor(travel)
    found = await executor.execute(
        run, "search_hotel_offers", {"expected_revision": request.revision, "limit": 5}
    )
    assert found.code is None
    offers = found.data["offers"]
    assert isinstance(offers, list) and offers
    presented = await executor.execute(
        run,
        "present_travel_result",
        {
            "component": "hotel_comparison",
            "expected_revision": request.revision,
            "offer_ids": [offer["offer_id"] for offer in offers],
        },
    )
    assert presented.code is None
    segments = presented.data["segments"]  # 单城市也带segments（一个住宿段）
    assert isinstance(segments, list) and len(segments) == 1
    return offers


def test_single_city_waits_for_a_selected_hotel_and_the_button_releases_planning(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup
    service = RunService(
        travel.database, runtime_factory=lambda _: WaitingRuntime(RuntimeOutcome(text="x"))
    )

    async def exercise() -> None:
        await known(travel, context)
        run = await run_of(travel, context)
        await goals(travel, run, "itinerary")
        tools = DatabaseTools(asyncio.get_running_loop(), travel.database)
        state = await travel.business_context(run)
        assert state["requires_hotel_selection"] is True
        offers = await shown_hotels(travel, run)
        assert len(offers) >= 2  # 展示全部候选，不替用户挑
        state = await travel.business_context(run)
        assert state["awaiting_hotel_selection"] is True and "selected_hotel_stays" not in state
        for name in ("estimate_routes", "validate_itinerary", "stage_plan_change"):
            result = await tools.execute(run, name, {})
            assert result.detail == ("hotel_selection_required",)
        assert await tools.continuation_reason(run, 1) is None  # 不催着继续，也不自动选
        view = await HotelSelectionService(travel).view(context.user_id, context.session_id)
        assert view.state == "awaiting" and view.can_skip and view.segments[0].selected is None
        await finish(travel, run)
        request = await travel.read_request(context)
        chosen = offers[1]
        assert request.start_date and request.end_date
        stay = HotelStay(
            check_in=request.start_date, check_out=request.end_date,
            hotel_evidence_id=UUID(str(chosen["evidence_id"])),
        )  # fmt: skip
        submitted = await service.submit(
            context.user_id,
            context.session_id,
            MessageInput(
                client_message_id=uuid4(), text="我选这家", expected_revision=request.revision,
                hotel_stays=(stay,),
            ),
        )  # fmt: skip
        active = RunContext(context.user_id, context.session_id, submitted.run_id)
        state = await travel.business_context(active)
        assert not state["requires_hotel_selection"]
        assert state["selected_hotel_stays"] == [stay.model_dump(mode="json")]
        view = await HotelSelectionService(travel).view(context.user_id, context.session_id)
        assert view.state == "complete" and not view.can_skip
        assert view.segments[0].selected is not None
        assert view.segments[0].selected.hotel_name == chosen["hotel_name"]
        assert view.segments[0].selected.source == "button"
        gated = await tools.execute(active, "estimate_routes", {})
        assert gated.detail != ("hotel_selection_required",)
        await service.cancel(context.user_id, submitted.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        await service.close()

    runner.run(exercise())


def test_skip_hotels_releases_the_gate_marks_lodging_unknown_and_is_validated(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup
    service = RunService(
        travel.database, runtime_factory=lambda _: WaitingRuntime(RuntimeOutcome(text="x"))
    )

    async def exercise() -> None:
        await known(travel, context)
        run = await run_of(travel, context)
        await goals(travel, run, "itinerary")
        await shown_hotels(travel, run)
        await finish(travel, run)
        request = await travel.read_request(context)
        stale = MessageInput(
            client_message_id=uuid4(), text="先排行程", expected_revision=request.revision + 1,
            skip_hotels=True,
        )  # fmt: skip
        with pytest.raises(ServiceError) as conflict:
            await service.submit(context.user_id, context.session_id, stale)
        assert conflict.value.status == 409
        with pytest.raises(ValueError):
            MessageInput(client_message_id=uuid4(), text="x", skip_hotels=True)  # 缺revision
        with pytest.raises(ValueError):
            MessageInput(
                client_message_id=uuid4(), text="x", expected_revision=1, skip_hotels=True,
                hotel_stays=(
                    HotelStay(
                        check_in=date(2026, 11, 3),
                        check_out=date(2026, 11, 5),
                        hotel_evidence_id=uuid4(),
                    ),
                ),
            )  # fmt: skip
        submitted = await service.submit(
            context.user_id, context.session_id,
            MessageInput(
                client_message_id=uuid4(), text="先不选酒店，先排行程",
                expected_revision=request.revision, skip_hotels=True,
            ),
        )  # fmt: skip
        active = RunContext(context.user_id, context.session_id, submitted.run_id)
        state = await travel.business_context(active)
        assert not state["requires_hotel_selection"] and state["lodging_skipped"] is True
        assert (await travel.read_request(context)).lodging_skipped
        view = await HotelSelectionService(travel).view(context.user_id, context.session_id)
        assert view.state == "skipped" and not view.can_skip
        tools = DatabaseTools(asyncio.get_running_loop(), travel.database)
        assert (await tools.execute(active, "estimate_routes", {})).detail != (
            "hotel_selection_required",
        )
        await service.cancel(context.user_id, submitted.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        await service.close()

    runner.run(exercise())


def test_skip_is_rejected_without_lodging_nights(travel_setup: Setup) -> None:
    runner, travel, context = travel_setup
    service = RunService(travel.database)

    async def exercise() -> None:
        request = await known(travel, context, end_date="2026-11-03")
        with pytest.raises(ServiceError) as rejected:
            await service.submit(
                context.user_id, context.session_id,
                MessageInput(
                    client_message_id=uuid4(), text="跳过", expected_revision=request.revision,
                    skip_hotels=True,
                ),
            )  # fmt: skip
        assert rejected.value.status == 422
        await service.close()

    runner.run(exercise())


# ---------------- 聊天选酒店（单城市） ----------------


LINK = "我看到乐天这家很好，就住这个 https://hotel.travel.rakuten.co.jp/hotelinfo/plan/?f_no={no}&f_flg=PLAN"


def test_single_city_chat_link_selects_through_the_same_validation(
    travel_setup: Setup, numeric_hotels: None
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await known(travel, context)
        first = await run_of(travel, context)
        await goals(travel, first, "itinerary")
        await finish(travel, first)
        run = await run_of(travel, context, LINK.format(no=70003))
        request = await travel.read_request(run)
        executor = FreshExecutor(travel)
        # 模型不能自带酒店身份
        extra = await executor.execute(
            run,
            "select_hotel_from_chat",
            {"expected_revision": request.revision, "hotel_id": "70003"},
        )
        assert extra.code == "validation"
        stale = await executor.execute(run, "select_hotel_from_chat", {"expected_revision": 99})
        assert stale.code == "conflict"
        result = await executor.execute(
            run, "select_hotel_from_chat", {"expected_revision": request.revision}
        )
        assert result.code is None and result.data["status"] == "selected"
        assert result.data["all_selected"] is True and result.data["remaining_segments"] == []
        state = await travel.business_context(run)
        stays = state["selected_hotel_stays"]
        assert isinstance(stays, list) and len(stays) == 1 and not state["requires_hotel_selection"]
        view = await HotelSelectionService(travel).view(context.user_id, context.session_id)
        assert view.state == "complete" and view.segments[0].selected is not None
        assert view.segments[0].selected.source == "chat"
        # 再说一次同一家：幂等
        again = await executor.execute(
            run, "select_hotel_from_chat", {"expected_revision": request.revision}
        )
        assert again.data["status"] == "nothing_to_select"

    runner.run(exercise())


def test_single_city_chat_name_matches_only_shown_candidates(
    travel_setup: Setup, numeric_hotels: None
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await known(travel, context)
        first = await run_of(travel, context)
        await goals(travel, first, "itinerary")
        offers = await shown_hotels(travel, first)
        name = str(offers[0]["hotel_name"])
        await finish(travel, first)
        executor = FreshExecutor(travel)
        request = await travel.read_request(context)
        unmatched = await run_of(travel, context, "就住那家有温泉的旅馆")
        miss = await executor.execute(
            unmatched, "select_hotel_from_chat", {"expected_revision": request.revision}
        )
        assert miss.data["status"] == "need_link"
        await finish(travel, unmatched)
        named = await run_of(travel, context, f"就住{name}这家")
        hit = await executor.execute(
            named, "select_hotel_from_chat", {"expected_revision": request.revision}
        )
        assert hit.data["status"] == "selected" and hit.data["hotel_name"] == name
        await finish(travel, named)
        unknown = await run_of(travel, context, LINK.format(no=99999))
        gone = await executor.execute(
            unknown, "select_hotel_from_chat", {"expected_revision": request.revision}
        )
        assert gone.data["status"] == "not_found"

    runner.run(exercise())


def test_chat_link_to_a_hotel_with_no_quote_leaves_selection_open(
    travel_setup: Setup, numeric_hotels: None
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await known(travel, context)
        run = await run_of(travel, context, LINK.format(no=99999))
        await goals(travel, run, "itinerary")
        request = await travel.read_request(run)
        result = await FreshExecutor(travel).execute(
            run, "select_hotel_from_chat", {"expected_revision": request.revision}
        )
        assert result.data["status"] == "not_found"
        view = await HotelSelectionService(travel).view(context.user_id, context.session_id)
        assert view.state == "awaiting" and view.can_skip

    runner.run(exercise())


# ---------------- 聊天选酒店（多城市）与归段确认卡 ----------------

NAMES = {
    "70001": ("白鹭庭院酒店", "京都"),
    "70002": ("鹿苑小筑酒店", "京都"),
    "70011": ("天守阁酒店", "大阪"),
    "70012": ("道顿堀之宿酒店", "大阪"),
}


async def two_city_quotes(
    travel: TravelService, context: RunContext
) -> tuple[TravelRequest, dict[str, EvidenceRecord]]:
    changed = await travel.patch_request(
        context,
        RequestPatch.model_validate(
            {
                "expected_revision": (await travel.read_request(context)).revision,
                "set": {
                    **KNOWN,
                    "segments": [
                        {"city": "京都", "arrive": "2026-11-03", "depart": "2026-11-04"},
                        {"city": "大阪", "arrive": "2026-11-04", "depart": "2026-11-05"},
                    ],
                },
            }
        ),
    )
    request = changed.request
    rates, _ = load_rates()
    records: dict[str, EvidenceRecord] = {}
    now = datetime.now(UTC)
    for segment in trip_segments(request):
        scoped = segment_request(request, segment)
        for hotel_id, (name, city) in NAMES.items():
            if city != segment.city:
                continue
            rate: HotelRate = rates[0].model_copy(
                update={"city": city, "hotel_id": hotel_id, "hotel_name": name}
            )
            offer = quote(rate, scoped, now)
            assert offer is not None
            records[hotel_id] = EvidenceRecord(
                entity_id=str(offer.offer_id),
                field_path="hotel_offer",
                value=offer.model_dump(mode="json"),
                kind="hotel_offer",
                request_revision=request.revision,
                conditions=evidence_conditions(scoped, "hotel_offer"),
                provider="fictional-hotels",
                source_ref="fixture:ask-and-select",
                content_version="synthetic-v1",
                data_mode="fixture",
                retrieved_at=now,
                valid_until=offer.expires_at,
                display_details=StoredHotelDetails(address=f"{city}府{city}市1-1"),
            )
    await travel.record_evidence(context, list(records.values()))
    return request, records


def test_multi_city_unstated_city_asks_for_assignment_and_confirm_records_the_pick(
    travel_setup: Setup, numeric_hotels: None
) -> None:
    runner, travel, context = travel_setup
    service = RunService(
        travel.database, runtime_factory=lambda _: WaitingRuntime(RuntimeOutcome(text="x"))
    )

    async def exercise() -> None:
        request, records = await two_city_quotes(travel, context)
        prior = await run_of(travel, context)
        await goals(travel, prior, "itinerary")
        await finish(travel, prior)
        run = await run_of(travel, context, LINK.format(no=70011))
        executor = FreshExecutor(travel)
        result = await executor.execute(
            run, "select_hotel_from_chat", {"expected_revision": request.revision}
        )
        assert result.data["status"] == "needs_confirmation"
        card = choice_card(result.data)
        assert card.kind == "hotel_assign" and card.assign and card.assign.city == "大阪"
        assert card.question == "因为你没说，已自动归到大阪的住宿段，可以吗？"
        assert [o.label for o in card.options] == ["确认", "否"]
        view = await HotelSelectionService(travel).view(context.user_id, context.session_id)
        assert view.state == "awaiting" and all(s.selected is None for s in view.segments)
        await finish(travel, run)
        submitted = await service.submit(
            context.user_id, context.session_id, submit_message(request, card, "confirm")
        )
        view = await HotelSelectionService(travel).view(context.user_id, context.session_id)
        osaka = next(s for s in view.segments if s.city == "大阪")
        assert osaka.selected and osaka.selected.source == "assign_confirm"
        assert osaka.selected.evidence_id == records["70011"].evidence_id
        assert view.state == "awaiting"
        # 用户在聊天里点名城市：不再确认，直接记录；两段选齐即放行规划
        await service.cancel(context.user_id, submitted.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        stated = await run_of(travel, context, "京都这边选 " + LINK.format(no=70001))
        done = await executor.execute(
            stated, "select_hotel_from_chat", {"expected_revision": request.revision}
        )
        assert done.data["status"] == "selected" and done.data["all_selected"] is True
        state = await travel.business_context(stated)
        assert not state["requires_hotel_selection"]
        chosen_stays = state["selected_hotel_stays"]
        assert isinstance(chosen_stays, list)
        assert [s["hotel_evidence_id"] for s in chosen_stays] == [
            str(records["70001"].evidence_id),
            str(records["70011"].evidence_id),
        ]
        await service.close()

    runner.run(exercise())


def test_multi_city_deny_with_city_reassigns_and_unknown_city_asks_again(
    travel_setup: Setup, numeric_hotels: None
) -> None:
    runner, travel, context = travel_setup
    service = RunService(
        travel.database, runtime_factory=lambda _: WaitingRuntime(RuntimeOutcome(text="x"))
    )

    async def exercise() -> None:
        request, records = await two_city_quotes(travel, context)
        prior = await run_of(travel, context)
        await goals(travel, prior, "itinerary")
        await finish(travel, prior)
        executor = FreshExecutor(travel)

        async def ask_card(number: int) -> ChoiceCard:
            run = await run_of(travel, context, LINK.format(no=number))
            data = (
                await executor.execute(
                    run, "select_hotel_from_chat", {"expected_revision": request.revision}
                )
            ).data
            await finish(travel, run)
            return choice_card(data)

        # 否 + 不存在的城市：不静默失败，再发一张填城市的卡
        card = await ask_card(70012)
        with pytest.raises(ServiceError):  # deny必须带城市
            await service.submit(
                context.user_id, context.session_id, submit_message(request, card, "deny")
            )
        wrong = await service.submit(
            context.user_id,
            context.session_id,
            submit_message(request, card, "deny", city=["名古屋"]),
        )
        active = RunContext(context.user_id, context.session_id, wrong.run_id)
        again = await executor.execute(
            active, "select_hotel_from_chat", {"expected_revision": request.revision}
        )
        assert again.data["status"] == "needs_confirmation"
        need = choice_card(again.data)
        assert need.assign and need.assign.needs_city
        assert {o.option_id for o in need.options} == {"deny", "dismiss"}
        await service.cancel(context.user_id, wrong.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        # 再答大阪：按答案归段并记录
        right = await service.submit(
            context.user_id,
            context.session_id,
            submit_message(request, need, "deny", city=["大阪"]),
        )
        active = RunContext(context.user_id, context.session_id, right.run_id)
        picked = await executor.execute(
            active, "select_hotel_from_chat", {"expected_revision": request.revision}
        )
        assert picked.data["status"] == "selected"
        view = await HotelSelectionService(travel).view(context.user_id, context.session_id)
        osaka = next(s for s in view.segments if s.city == "大阪")
        assert osaka.selected and osaka.selected.evidence_id == records["70012"].evidence_id
        assert osaka.selected.source == "chat"
        await service.cancel(context.user_id, right.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        await service.close()

    runner.run(exercise())


def test_dismissing_the_assignment_card_records_nothing(
    travel_setup: Setup, numeric_hotels: None
) -> None:
    runner, travel, context = travel_setup
    service = RunService(
        travel.database, runtime_factory=lambda _: WaitingRuntime(RuntimeOutcome(text="x"))
    )

    async def exercise() -> None:
        request, _ = await two_city_quotes(travel, context)
        prior = await run_of(travel, context)
        await goals(travel, prior, "itinerary")
        await finish(travel, prior)
        executor = FreshExecutor(travel)
        run = await run_of(travel, context, "就住" + NAMES["70002"][0] + "吧")
        data = (
            await executor.execute(
                run, "select_hotel_from_chat", {"expected_revision": request.revision}
            )
        ).data
        card = choice_card(data)  # 只说了名字、没说城市：按候选所在城市暂归并确认
        assert card.assign and card.assign.city == "京都"
        await finish(travel, run)
        denied = await service.submit(
            context.user_id,
            context.session_id,
            submit_message(request, card, "deny", city=["名古屋"]),
        )
        active = RunContext(context.user_id, context.session_id, denied.run_id)
        need = choice_card(
            (
                await executor.execute(
                    active, "select_hotel_from_chat", {"expected_revision": request.revision}
                )
            ).data
        )
        await service.cancel(context.user_id, denied.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        with pytest.raises(ServiceError):  # dismiss不接受答案
            await service.submit(
                context.user_id,
                context.session_id,
                submit_message(request, need, "dismiss", city=["京都"]),
            )
        dismissed = await service.submit(
            context.user_id, context.session_id, submit_message(request, need, "dismiss")
        )
        view = await HotelSelectionService(travel).view(context.user_id, context.session_id)
        assert view.state == "awaiting" and all(s.selected is None for s in view.segments)
        restored = await ChoiceService(travel).get(
            context.user_id, context.session_id, need.choice_id
        )
        assert restored.answered_option_id == "dismiss"
        await service.cancel(context.user_id, dismissed.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        await service.close()

    runner.run(exercise())


def test_choice_row_kind_is_persisted_and_old_assignment_cards_are_superseded(
    travel_setup: Setup, numeric_hotels: None
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        request, _ = await two_city_quotes(travel, context)
        prior = await run_of(travel, context)
        await goals(travel, prior, "itinerary")
        await finish(travel, prior)
        executor = FreshExecutor(travel)
        cards = []
        for number in (70011, 70012):
            run = await run_of(travel, context, LINK.format(no=number))
            data = (
                await executor.execute(
                    run, "select_hotel_from_chat", {"expected_revision": request.revision}
                )
            ).data
            cards.append(choice_card(data))
            await finish(travel, run)
        old = await ChoiceService(travel).get(
            context.user_id, context.session_id, cards[0].choice_id
        )
        newest = await ChoiceService(travel).get(
            context.user_id, context.session_id, cards[1].choice_id
        )
        assert old.stale and not newest.stale
        async with transaction(travel.database) as db:
            row = await db.get(ChoiceCardRow, cards[1].choice_id)
            assert row is not None and row.kind == "hotel_assign"

    runner.run(exercise())

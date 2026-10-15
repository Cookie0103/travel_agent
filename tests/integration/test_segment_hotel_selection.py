"""R04/R05/R06/R08：分段候选、完整酒店选择与规范引用使用真实 PostgreSQL。"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.domain.conversation import ConversationStateInput
from backend.domain.evidence import EvidenceRecord, evidence_conditions
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.domain.hotel_details import StoredHotelDetails
from backend.domain.hotels import HotelOffer, quote
from backend.domain.itinerary import HotelStay, ItineraryProposal
from backend.domain.plans import StageInput
from backend.domain.travel_request import (
    RequestPatch,
    TravelRequest,
    segment_request,
    trip_segments,
)
from backend.persistence.models import EvidenceRow, PlanVersionRow
from backend.providers.claude_agent.database_tools import DatabaseTools
from backend.providers.hotel_fixture import load_rates
from backend.services.common import ServiceError, transaction
from backend.services.planning import PlanningService
from backend.services.plans import PlanService
from backend.services.runs import MessageInput, RunService
from backend.services.travel import TravelService
from backend.tools.travel import TravelToolExecutor
from tests.integration.test_conversation_state import create_run, finish
from tests.integration.test_runs import WaitingRuntime
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_multi_city_itinerary import multi_city_example

pytestmark = pytest.mark.integration


async def three_city_quotes(
    travel: TravelService, context: RunContext
) -> tuple[TravelRequest, tuple[EvidenceRecord, ...]]:
    changed = await travel.patch_request(
        context,
        RequestPatch.model_validate(
            {
                "expected_revision": 1,
                "set": {
                    "city": "大阪",
                    "end_date": "2026-11-06",
                    "segments": [
                        {"city": "大阪", "arrive": "2026-11-03", "depart": "2026-11-04"},
                        {"city": "京都", "arrive": "2026-11-04", "depart": "2026-11-05"},
                        {"city": "奈良", "arrive": "2026-11-05", "depart": "2026-11-06"},
                    ],
                },
            }
        ),
    )
    records: list[EvidenceRecord] = []
    rates, _ = load_rates()
    now = datetime.now(UTC)
    for segment in trip_segments(changed.request):
        scoped = segment_request(changed.request, segment)
        for index in range(3):
            offer = quote(
                rates[0].model_copy(update={"city": segment.city, "hotel_id": str(index)}),
                scoped,
                now,
            )
            assert offer is not None
            records.append(
                EvidenceRecord(
                    entity_id=str(offer.offer_id),
                    field_path="hotel_offer",
                    value=offer.model_dump(mode="json"),
                    kind="hotel_offer",
                    request_revision=changed.request.revision,
                    conditions=evidence_conditions(scoped, "hotel_offer"),
                    provider="fictional-hotels",
                    source_ref="fixture:segment-hotel-selection",
                    content_version="synthetic-v1",
                    data_mode="fixture",
                    retrieved_at=now,
                    valid_until=offer.expires_at,
                    display_details=StoredHotelDetails(
                        search_total_found=100 + len(records),
                        more_url=f"https://travel.rakuten.co.jp/{segment.arrive}.html",
                        more_url_scope="destination",
                    ),
                )
            )
    await travel.record_evidence(context, records)
    return changed.request, tuple(records)


def test_three_city_presentation_has_independent_rows_and_accepts_nine_offers(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        request, records = await three_city_quotes(travel, context)
        executor = TravelToolExecutor(travel)
        result = await executor.execute(
            context,
            "present_travel_result",
            {
                "component": "hotel_comparison",
                "expected_revision": request.revision,
                "offer_ids": [record.entity_id for record in records],
            },
        )
        assert result.code is None
        segments = result.data["segments"]
        assert isinstance(segments, list) and len(segments) == 3
        for index, segment in enumerate(segments):
            assert isinstance(segment, dict)
            assert segment["city"] == ("大阪", "京都", "奈良")[index]
            assert segment["evidence_ids"] == [
                str(record.evidence_id) for record in records[index * 3 : (index + 1) * 3]
            ]
            assert segment["total_found"] == 100 + index * 3
            assert str(segment["check_in"]) in str(segment["more_url"])
            comparison = segment["comparison"]
            assert isinstance(comparison, dict) and comparison["comparable"] is True
        presented = result.data["cards"]
        assert isinstance(presented, list) and len(presented) == 9
        assert await travel.get_request(context) == request

    runner.run(exercise())


def selection_message(revision: int, stays: tuple[HotelStay, ...]) -> MessageInput:
    return MessageInput(
        client_message_id=uuid4(),
        text="按已选的各段酒店规划。",
        expected_revision=revision,
        hotel_stays=stays,
    )


def test_all_selected_stays_survive_model_omission_stage_and_restore(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    runtime = WaitingRuntime(RuntimeOutcome(text="合成执行", sdk_session_id="synthetic"))
    service = RunService(travel.database, runtime_factory=lambda _: runtime)

    async def exercise() -> None:
        request, proposal, records = multi_city_example()
        changed = await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": request.model_dump(exclude={"revision"}, exclude_none=True),
                }
            ),
        )
        revision = changed.request.revision
        await travel.record_evidence(context, records)
        message = selection_message(revision, proposal.hotel_stays)
        submitted = await service.submit(context.user_id, context.session_id, message)
        active = RunContext(context.user_id, context.session_id, submitted.run_id)
        omitted = ItineraryProposal.model_validate(
            {"expected_revision": revision, "items": proposal.model_dump(mode="json")["items"]}
        )
        report = await PlanningService(travel).validate(active, omitted)
        assert not any(check.code == "hotel_stay_missing" for check in report.checks)
        state = await travel.business_context(active)
        assert state["selected_hotel_stays"] == [
            stay.model_dump(mode="json") for stay in proposal.hotel_stays
        ]
        explicit_clear = omitted.model_copy(update={"hotel_stays": ()})
        with pytest.raises(ServiceError, match="用户已选择"):
            await PlanningService(travel).validate(active, explicit_clear)
        drafts = PlanService(travel)
        draft = await drafts.stage(
            active,
            StageInput.model_validate(
                {"change": {"kind": "initial", "proposal": omitted.model_dump(exclude_unset=True)}}
            ),
        )
        assert draft.content.hotel_stays == proposal.hotel_stays
        saved = await drafts.confirm(context.user_id, draft.draft_id)
        restored = await PlanService(TravelService(travel.database)).get(
            context.user_id, saved.plan_id
        )
        restored_stays = restored["hotel_stays"]
        assert isinstance(restored_stays, list)
        assert [stay["hotel_evidence_id"] for stay in restored_stays] == [
            str(stay.hotel_evidence_id) for stay in proposal.hotel_stays
        ]
        clears: tuple[dict[str, object], ...] = (
            {"hotel_evidence_id": None},
            {"hotel_stays": []},
        )
        for clear in clears:
            with pytest.raises(ServiceError, match="用户已选择"):
                await drafts.stage(
                    active,
                    StageInput.model_validate(
                        {
                            "change": {
                                "kind": "patch",
                                "plan_id": str(saved.plan_id),
                                "patch": {
                                    "expected_revision": revision,
                                    "base_version": saved.version,
                                    **clear,
                                },
                            }
                        }
                    ),
                )
        # 合成旧行程无住宿引用的恢复点；先在未选择的另一轮留下项目patch缓存。
        async with transaction(travel.database) as db:
            version = await db.get(PlanVersionRow, (saved.plan_id, saved.version))
            assert version is not None
            old_content = saved.content.model_copy(update={"hotel_stays": ()})
            version.payload = saved.model_copy(update={"content": old_content}).model_dump(
                mode="json"
            )
        first_item = saved.content.items[0]
        patch = StageInput.model_validate(
            {
                "change": {
                    "kind": "patch",
                    "plan_id": str(saved.plan_id),
                    "patch": {
                        "expected_revision": revision,
                        "base_version": saved.version,
                        "operations": [
                            {
                                "op": "update",
                                "item_id": str(first_item.item_id),
                                "item": first_item.proposed().model_dump(mode="json"),
                            }
                        ],
                    },
                }
            }
        )
        old = await drafts.stage(RunContext(context.user_id, context.session_id), patch)
        assert not old.content.hotel_stays
        with pytest.raises(ServiceError, match="缓存草稿"):
            await drafts.stage(active, patch)
        await service.cancel(context.user_id, submitted.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        await travel.patch_request(
            context,
            RequestPatch.model_validate({"expected_revision": revision, "set": {"budget": 600000}}),
        )
        replay = await service.submit(context.user_id, context.session_id, message)
        assert replay.run_id == submitted.run_id
        altered = message.model_copy(
            update={
                "hotel_stays": (
                    proposal.hotel_stays[0].model_copy(update={"hotel_evidence_id": uuid4()}),
                )
            }
        )
        with pytest.raises(ServiceError, match="同一消息ID"):
            await service.submit(context.user_id, context.session_id, altered)
        await service.close()

    runner.run(exercise())


@pytest.mark.parametrize("bad", ["missing", "dates", "unknown", "revision", "expired"])
def test_incomplete_or_invalid_hotel_selection_never_starts_run(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], bad: str
) -> None:
    runner, travel, context = travel_setup
    service = RunService(travel.database)

    async def exercise() -> None:
        request, records = await three_city_quotes(travel, context)
        stays = tuple(
            HotelStay(
                check_in=segment.arrive,
                check_out=segment.depart,
                hotel_evidence_id=records[index * 3].evidence_id,
            )
            for index, segment in enumerate(trip_segments(request))
        )
        if bad == "missing":
            stays = stays[:2]
        elif bad == "dates":
            stays = (stays[0].model_copy(update={"check_out": stays[1].check_out}), *stays[1:])
        elif bad == "unknown":
            stays = (stays[0].model_copy(update={"hotel_evidence_id": uuid4()}), *stays[1:])
        elif bad == "expired":
            async with transaction(travel.database) as db:
                row = await db.get(EvidenceRow, records[0].evidence_id)
                assert row is not None
                row.payload = {
                    **row.payload,
                    "retrieved_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                    "valid_until": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                }
        message = selection_message(request.revision - (bad == "revision"), stays)
        with pytest.raises(ServiceError):
            await service.submit(context.user_id, context.session_id, message)
        assert not service.tasks
        assert await travel.get_request(context) == request

    runner.run(exercise())


def test_initial_planning_waits_for_segment_selection_and_stop_hook_does_not_push_past_it(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        request, records = await three_city_quotes(travel, context)
        request = (
            await travel.patch_request(
                context,
                RequestPatch.model_validate(
                    {
                        "expected_revision": request.revision,
                        "set": {
                            "lodging_budget_unlimited": True,
                            "transport": "transit",
                            "soft_constraints": ["节奏：标准"],
                        },
                    }
                ),
            )
        ).request
        active = await create_run(travel, context, "合成三城市酒店和行程")
        await travel.update_conversation_state(
            active, ConversationStateInput(expected_revision=request.revision, goals=("itinerary",))
        )
        tools = DatabaseTools(asyncio.get_running_loop(), travel.database)
        for name in ("estimate_routes", "validate_itinerary", "stage_plan_change"):
            result = await tools.execute(active, name, {})
            assert result.code == "validation" and result.detail == ("hotel_selection_required",)
        assert tools.executor.calls == 0
        assert await tools.continuation_reason(active, 1) is not None
        result = await tools.execute(
            active,
            "present_travel_result",
            {
                "component": "hotel_comparison",
                "expected_revision": request.revision,
                "offer_ids": [record.entity_id for record in records],
            },
        )
        assert result.code is None
        assert await tools.continuation_reason(active, 1) is None
        state = await travel.business_context(active)
        assert state["awaiting_hotel_selection"] is True
        await finish(travel, active)
        next_turn = await create_run(travel, context, "合成继续查看酒店")
        later = await travel.business_context(next_turn)
        assert not later["awaiting_hotel_selection"]
        assert await tools.continuation_reason(next_turn, 1) is not None
        await finish(travel, next_turn)
        stays = tuple(
            HotelStay(
                check_in=segment.arrive,
                check_out=segment.depart,
                hotel_evidence_id=records[index * 3].evidence_id,
            )
            for index, segment in enumerate(trip_segments(request))
        )
        runtime = WaitingRuntime(RuntimeOutcome(text="合成执行", sdk_session_id="synthetic"))
        service = RunService(travel.database, runtime_factory=lambda _: runtime)
        selected = await service.submit(
            context.user_id, context.session_id, selection_message(request.revision, stays)
        )
        selected_context = RunContext(context.user_id, context.session_id, selected.run_id)
        state = await travel.business_context(selected_context)
        assert not state["requires_hotel_selection"]
        chosen = state["selected_hotel_stays"]
        assert isinstance(chosen, list) and len(chosen) == 3
        other = await travel.business_context(context)
        assert "selected_hotel_stays" not in other
        await service.cancel(context.user_id, selected.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        await service.close()

    runner.run(exercise())


@pytest.mark.parametrize("case", ["question", "empty"])
def test_missing_segment_candidates_and_budget_question_do_not_start_planning(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    case: str,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        request, records = await three_city_quotes(travel, context)
        active = await create_run(travel, context, "合成酒店和行程")
        tools = DatabaseTools(asyncio.get_running_loop(), travel.database)
        await travel.update_conversation_state(
            active,
            ConversationStateInput(
                expected_revision=request.revision,
                goals=("itinerary",),
                awaiting_field="lodging_budget" if case == "question" else None,
            ),
        )
        if case == "question":
            assert await tools.continuation_reason(active, 1) is None
            return
        result = await tools.execute(
            active,
            "present_travel_result",
            {
                "component": "hotel_comparison",
                "expected_revision": request.revision,
                "offer_ids": [record.entity_id for record in records[:6]],
            },
        )
        assert result.code is None
        rows = result.data["segments"]
        assert isinstance(rows, list) and len(rows) == 3
        assert isinstance(rows[2], dict)
        assert rows[2]["city"] == "奈良" and rows[2]["evidence_ids"] == []
        assert rows[2]["comparison"]["comparable"] is False

    runner.run(exercise())


def test_stage_cache_does_not_restore_another_runs_selected_hotels(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    service = RunService(
        travel.database,
        runtime_factory=lambda _: WaitingRuntime(
            RuntimeOutcome(text="合成执行", sdk_session_id="synthetic")
        ),
    )

    async def exercise() -> None:
        request, proposal, records = multi_city_example()
        changed = await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": request.model_dump(exclude={"revision"}, exclude_none=True),
                }
            ),
        )
        revision = changed.request.revision
        await travel.record_evidence(context, records)
        original = await service.submit(
            context.user_id, context.session_id, selection_message(revision, proposal.hotel_stays)
        )
        active = RunContext(context.user_id, context.session_id, original.run_id)
        arguments = StageInput.model_validate(
            {
                "change": {
                    "kind": "initial",
                    "proposal": {
                        "expected_revision": revision,
                        "items": proposal.model_dump(mode="json")["items"],
                    },
                }
            }
        )
        drafts = PlanService(travel)
        old = await drafts.stage(active, arguments)
        await service.cancel(context.user_id, original.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        replacement = next(
            r for r in records if r.evidence_id == proposal.hotel_stays[0].hotel_evidence_id
        )
        original_offer = HotelOffer.model_validate(replacement.value)
        offer = original_offer.model_copy(update={"offer_id": uuid4()})
        replacement = replacement.model_copy(
            update={
                "evidence_id": uuid4(),
                "entity_id": str(offer.offer_id),
                "value": offer.model_dump(mode="json"),
            }
        )
        await travel.record_evidence(context, (replacement,))
        stays = (
            proposal.hotel_stays[0].model_copy(
                update={"hotel_evidence_id": replacement.evidence_id}
            ),
            *proposal.hotel_stays[1:],
        )
        selected = await service.submit(
            context.user_id, context.session_id, selection_message(revision, stays)
        )
        new = await drafts.stage(
            RunContext(context.user_id, context.session_id, selected.run_id), arguments
        )
        assert new.draft_id != old.draft_id
        assert new.content.hotel_stays == stays
        await service.cancel(context.user_id, selected.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        await service.close()

    runner.run(exercise())


def test_nine_full_cards_have_a_bounded_multi_segment_presentation_allowance(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R03：多段完整链接卡超过旧六卡大小时仍能展示，其他工具限制不变。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        request, records = await three_city_quotes(travel, context)
        complete = []
        long_url = "https://travel.rakuten.co.jp/hotel/?selection=" + "x" * 950
        for record in records:
            offer = HotelOffer.model_validate(record.value).model_copy(
                update={"offer_id": uuid4(), "booking_url": long_url}
            )
            assert record.display_details is not None
            complete.append(
                record.model_copy(
                    update={
                        "evidence_id": uuid4(),
                        "entity_id": str(offer.offer_id),
                        "value": offer.model_dump(mode="json"),
                        "display_details": record.display_details.model_copy(
                            update={
                                "hotel_info_url": long_url,
                                "plan_list_url": long_url,
                                "reservation_url": long_url,
                            }
                        ),
                    }
                )
            )
        await travel.record_evidence(context, complete)
        result = await TravelToolExecutor(travel).execute(
            context,
            "present_travel_result",
            {
                "component": "hotel_comparison",
                "expected_revision": request.revision,
                "offer_ids": [record.entity_id for record in complete],
            },
        )
        assert result.code is None
        assert 24000 < len(json.dumps(result.payload(), ensure_ascii=False)) < 3 * 24000

    runner.run(exercise())

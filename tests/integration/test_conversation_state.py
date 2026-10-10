"""B20/R13：真实PG澄清状态、原任务恢复与按实际工具结果推进。"""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeOutcome
from backend.domain.travel_request import RequestPatch
from backend.persistence import runs
from backend.services.common import transaction
from backend.services.travel import TravelService
from backend.tools.contracts import PRESENTATION_RESULT_LIMIT
from backend.tools.travel import TravelToolExecutor
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


async def create_run(travel: TravelService, context: RunContext, prompt: str) -> RunContext:
    async with transaction(travel.database) as db:
        row = await runs.create(
            db, context.user_id, context.session_id, uuid4(), prompt, "deepseek"
        )
        return replace(context, run_id=row.id)


async def finish(travel: TravelService, context: RunContext) -> None:
    async with transaction(travel.database) as db:
        await runs.finish(
            db,
            context,
            RuntimeOutcome(text="实时回复仅供本轮查看；详情按需更新。", sdk_session_id="synthetic"),
        )


def test_original_goal_and_bed_question_survive_three_rounds_without_supplier_text(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {
                        "hard_constraints": ["住宿：独立房间", "房型：禁烟"],
                        "soft_constraints": ["节奏：标准"],
                        "transport": "transit",
                        "start_date": "2026-10-11",
                        "end_date": "2026-10-12",
                    },
                }
            ),
        )
        origin = await create_run(travel, context, "合成用户任务：查酒店并规划行程")
        result = await TravelToolExecutor(travel).execute(
            origin,
            "update_conversation_state",
            {
                "expected_revision": 2,
                "goals": ["hotel_comparison", "itinerary"],
                "awaiting_field": "bed",
            },
        )
        assert result.code is None
        await finish(travel, origin)
        for prompt in ("没有小孩", "一间房", "住宿没有单独上限"):
            turn = await create_run(travel, context, prompt)
            await finish(travel, turn)
        state = await TravelService(travel.database).business_context(
            replace(context, run_id=uuid4())
        )
        dialogue = state["conversation"]
        assert isinstance(dialogue, dict)
        assert dialogue["goal_prompt"] == "合成用户任务：查酒店并规划行程"
        assert dialogue["awaiting_field"] == "bed"
        assert dialogue["missing_fields"] == ["bed"]
        assert dialogue["pending_tasks"] == ["hotel_comparison", "itinerary"]
        assert dialogue["nights"] == 1
        assert "住宿预算" not in str(dialogue["missing_fields"])
        assert "实时回复仅供" not in str(dialogue)
        answer = await create_run(travel, context, "都可以")
        receipt = await TravelToolExecutor(travel).execute(
            answer,
            "update_travel_request",
            {
                "expected_revision": 2,
                "set": {"hard_constraints": ["住宿：独立房间", "房型：禁烟", "床型：无要求"]},
                "explicit_fields": ["hard_constraints"],
            },
        )
        assert receipt.code is None
        current = (await travel.business_context(answer))["conversation"]
        assert isinstance(current, dict) and current["awaiting_field"] is None
        assert current["missing_fields"] == [] and current["ready_tasks"] == [
            "hotel_comparison",
            "itinerary",
        ]
        assert (await travel.get_request(answer)).lodging_budget is None
        assert (await travel.get_request(answer)).child_ages == ()

    runner.run(exercise())


@pytest.mark.parametrize("field", ["child_ages", "rooms", "bed", "lodging_budget"])
def test_known_or_optional_fields_cannot_be_recorded_as_required_question(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    field: str,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        turn = await create_run(travel, context, "合成用户任务")
        result = await TravelToolExecutor(travel).execute(
            turn,
            "update_conversation_state",
            {"expected_revision": 1, "goals": ["hotel_comparison"], "awaiting_field": field},
        )
        assert result.code == "validation"
        assert (await travel.get_request(turn)).revision == 1

    runner.run(exercise())


def test_successful_hotel_presentation_clears_task_but_sdk_finish_does_not(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        turn = await create_run(travel, context, "合成酒店比较任务")
        executor = TravelToolExecutor(travel)
        saved = await executor.execute(
            turn,
            "update_conversation_state",
            {"expected_revision": 1, "goals": ["hotel_comparison"]},
        )
        assert saved.code is None
        offers = await executor.execute(
            turn, "search_hotel_offers", {"expected_revision": 1, "limit": 1}
        )
        assert offers.code is None
        state = (await travel.business_context(turn))["conversation"]
        assert isinstance(state, dict) and state["pending_tasks"] == ["hotel_comparison"]
        cards = offers.data["offers"]
        assert isinstance(cards, list)
        shown = await executor.execute(
            turn,
            "present_travel_result",
            {
                "component": "hotel_comparison",
                "expected_revision": 1,
                "offer_ids": [card["offer_id"] for card in cards],
            },
        )
        assert shown.code is None
        state = (await travel.business_context(turn))["conversation"]
        assert isinstance(state, dict) and state["pending_tasks"] == []
        assert (await travel.get_request(turn)).revision == 1
        await finish(travel, turn)

    runner.run(exercise())


def test_native_sdk_stop_keeps_working_after_conditions_are_ready(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
) -> None:
    """B20：实际SDK/CLI首答想继续追问，Stop反馈让同一SDK执行真正查询展示。"""
    from backend.mcp.bridge import sdk_tool_name
    from tests.integration.sdk_helper import run_database_worker
    from tests.test_sdk_cli_offline import scripted_response

    runner, travel, context = travel_setup
    turn = runner.run(create_run(travel, context, "合成酒店比较任务"))
    saved = runner.run(
        TravelToolExecutor(travel).execute(
            turn,
            "update_conversation_state",
            {"expected_revision": 1, "goals": ["hotel_comparison"]},
        )
    )
    assert saved.code is None
    requests: list[dict[str, object]] = []

    def forward(body: bytes) -> tuple[int, bytes]:
        request = json.loads(body)
        requests.append(request)
        if len(requests) == 1:
            # 已知条件齐全，但模型首答尝试结束；必须经原生Stop反馈继续。
            return scripted_response(
                b'{"messages":[{"content":[{"type":"tool_result",'
                b'"content":"Synthetic premature answer"}]}]}'
            )
        if len(requests) == 2:
            return scripted_response(
                b'{"messages":[]}',
                tool_calls=(
                    (sdk_tool_name("search_hotel_offers"), {"expected_revision": 1, "limit": 1}),
                ),
            )
        if len(requests) == 3:
            results = [
                block
                for message in request["messages"]
                for block in message.get("content", [])
                if isinstance(block, dict) and block.get("type") == "tool_result"
            ]
            content = results[-1]["content"]
            payload = json.loads(content if isinstance(content, str) else content[0]["text"])
            return scripted_response(
                b'{"messages":[]}',
                tool_calls=(
                    (
                        sdk_tool_name("present_travel_result"),
                        {
                            "component": "hotel_comparison",
                            "expected_revision": 1,
                            "offer_ids": [card["offer_id"] for card in payload["data"]["offers"]],
                        },
                    ),
                ),
            )
        return scripted_response(body)

    result, guard = run_database_worker(
        travel, turn, tmp_path, forward, "都可以，继续之前的酒店比较", max_attempts=4
    )
    assert result["status"] == "success" and not guard.failures
    assert len(requests) == 4
    state = runner.run(travel.business_context(turn))["conversation"]
    assert isinstance(state, dict) and state["pending_tasks"] == []


def test_cancel_and_inactive_run_cannot_overwrite_new_task(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        old = await create_run(travel, context, "合成旧任务")
        executor = TravelToolExecutor(travel)
        assert (
            await executor.execute(
                old,
                "update_conversation_state",
                {"expected_revision": 1, "goals": ["hotel_comparison"]},
            )
        ).code is None
        assert (
            await executor.execute(
                old, "update_conversation_state", {"expected_revision": 1, "cancel": True}
            )
        ).code is None
        await finish(travel, old)
        current = await create_run(travel, context, "合成新任务")
        assert (
            await TravelToolExecutor(travel).execute(
                current,
                "update_conversation_state",
                {"expected_revision": 1, "goals": ["itinerary"]},
            )
        ).code is None
        rejected = await TravelToolExecutor(travel).execute(
            old,
            "update_conversation_state",
            {"expected_revision": 1, "goals": ["hotel_comparison"]},
        )
        assert rejected.code == "conflict"
        state = (await travel.business_context(current))["conversation"]
        assert isinstance(state, dict) and state["pending_tasks"] == ["itinerary"]
        assert state["goal_prompt"] == "合成新任务"
        assert (await travel.get_request(current)).revision == 1

    runner.run(exercise())


def test_state_rejects_cross_session_run_and_stale_revision(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    from backend.services.sessions import SessionService

    runner, travel, context = travel_setup

    async def exercise() -> None:
        turn = await create_run(travel, context, "合成任务")
        other = await SessionService(travel.database.engine.url).new_session(context.user_id)
        executor = TravelToolExecutor(travel)
        wrong = await executor.execute(
            replace(turn, session_id=other.session_id),
            "update_conversation_state",
            {"expected_revision": 0, "goals": ["hotel_comparison"]},
        )
        assert wrong.code == "conflict"
        stale = await TravelToolExecutor(travel).execute(
            turn,
            "update_conversation_state",
            {"expected_revision": 0, "goals": ["hotel_comparison"]},
        )
        assert stale.code == "conflict"
        state = (await travel.business_context(turn))["conversation"]
        assert isinstance(state, dict) and state["pending_tasks"] == []

    runner.run(exercise())


def test_conversation_bed_only_update_preserves_other_room_groups_and_manual_source(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
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
                            "住宿：独立房间",
                            "房型：禁烟",
                            "床型：大床",
                            "不坐飞机",
                            "返程当天16:00前到机场",
                        ]
                    },
                }
            ),
        )
        turn = await create_run(travel, context, "合成明确改值：床型都可以")
        executor = TravelToolExecutor(travel)
        skipped = await executor.execute(
            turn,
            "update_travel_request",
            {"expected_revision": 2, "set": {"hard_constraints": ["床型：都可以"]}},
        )
        assert skipped.data["skipped_fields"] == ("hard_constraints",)
        assert (await travel.get_request(turn)).revision == 2
        changed = await executor.execute(
            turn,
            "update_travel_request",
            {
                "expected_revision": 2,
                "set": {"hard_constraints": ["床型：都可以"]},
                "explicit_fields": ["hard_constraints"],
            },
        )
        assert changed.code is None
        assert set((await travel.get_request(turn)).hard_constraints) == {
            "住宿：独立房间",
            "房型：禁烟",
            "床型：无要求",
            "不坐飞机",
            "返程当天16:00前到机场",
        }
        equivalent = await executor.execute(
            turn,
            "update_travel_request",
            {
                "expected_revision": 3,
                "set": {"hard_constraints": ["床型：无要求"]},
                "explicit_fields": ["hard_constraints"],
            },
        )
        assert equivalent.data["changed_fields"] == ()
        assert (await travel.get_request(turn)).revision == 3

    runner.run(exercise())


def test_oversized_presentation_keeps_task_pending(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        turn = await create_run(travel, context, "合成酒店比较任务")
        executor = TravelToolExecutor(travel)
        assert (
            await executor.execute(
                turn,
                "update_conversation_state",
                {"expected_revision": 1, "goals": ["hotel_comparison"]},
            )
        ).code is None
        offers = await executor.execute(
            turn, "search_hotel_offers", {"expected_revision": 1, "limit": 1}
        )
        cards = offers.data["offers"]
        assert isinstance(cards, list)
        original = executor.hotels.present

        async def long_result(
            context: RunContext, revision: int, ids: tuple[UUID, ...]
        ) -> dict[str, object]:
            result = await original(context, revision, ids)
            result["synthetic_large_text"] = "x" * PRESENTATION_RESULT_LIMIT
            return result

        monkeypatch.setattr(executor.hotels, "present", long_result)
        result = await executor.execute(
            turn,
            "present_travel_result",
            {
                "component": "hotel_comparison",
                "expected_revision": 1,
                "offer_ids": [card["offer_id"] for card in cards],
            },
        )
        assert result.code == "blocked" and "result_too_long" in result.detail
        state = (await travel.business_context(turn))["conversation"]
        assert isinstance(state, dict) and state["pending_tasks"] == ["hotel_comparison"]

    runner.run(exercise())


def test_itinerary_missing_local_transport_can_clarify_without_forced_execution(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {"expected_revision": 1, "set": {"soft_constraints": ["节奏：标准"]}}
            ),
        )
        turn = await create_run(travel, context, "合成行程任务")
        result = await TravelToolExecutor(travel).execute(
            turn,
            "update_conversation_state",
            {"expected_revision": 2, "goals": ["itinerary"], "awaiting_field": "transport"},
        )
        assert result.code is None
        state = (await travel.business_context(turn))["conversation"]
        assert isinstance(state, dict) and state["missing_fields"] == ["transport"]
        assert state["ready_tasks"] == []

    runner.run(exercise())


def test_explicit_non_room_removal_keeps_other_hard_constraints(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
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
                            "住宿：独立房间",
                            "房型：禁烟",
                            "床型：大床",
                            "不坐飞机",
                            "返程当天16:00前到机场",
                        ]
                    },
                }
            ),
        )
        turn = await create_run(travel, context, "合成用户明确允许飞机，保留其他要求")
        result = await TravelToolExecutor(travel).execute(
            turn,
            "update_travel_request",
            {
                "expected_revision": 2,
                "set": {"hard_constraints": []},
                "remove_hard_constraints": ["不坐飞机"],
                "explicit_fields": ["hard_constraints"],
            },
        )
        assert result.code is None
        current = await travel.get_request(turn)
        assert "不坐飞机" not in current.hard_constraints
        assert "返程当天16:00前到机场" in current.hard_constraints
        assert "房型：禁烟" in current.hard_constraints

    runner.run(exercise())


def test_new_same_kind_goal_after_privacy_tombstone_uses_new_user_prompt(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    from backend.services.preferences import PreferenceService, PreferenceVersion

    runner, travel, context = travel_setup

    async def exercise() -> None:
        old = await create_run(travel, context, "合成墓碑前任务，不应恢复")
        assert (
            await TravelToolExecutor(travel).execute(
                old,
                "update_conversation_state",
                {"expected_revision": 1, "goals": ["hotel_comparison"]},
            )
        ).code is None
        await finish(travel, old)
        await PreferenceService(travel.database).change(
            context.user_id, PreferenceVersion(expected_revision=0)
        )
        hidden = (await travel.business_context(context))["conversation"]
        assert (
            isinstance(hidden, dict)
            and hidden["pending_tasks"] == []
            and hidden["goal_prompt"] is None
        )
        new = await create_run(travel, context, "合成墓碑后重新授权的酒店任务")
        assert (
            await TravelToolExecutor(travel).execute(
                new,
                "update_conversation_state",
                {"expected_revision": 1, "goals": ["hotel_comparison"]},
            )
        ).code is None
        visible = (await travel.business_context(new))["conversation"]
        assert isinstance(visible, dict) and visible["pending_tasks"] == ["hotel_comparison"]
        assert visible["goal_prompt"] == "合成墓碑后重新授权的酒店任务"

    runner.run(exercise())


def test_nonempty_constraint_removal_cannot_replay_legacy_no_removal_receipt(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    from backend.domain.travel_request import legacy_request
    from backend.persistence import operations
    from backend.persistence import travel as repository

    runner, travel, context = travel_setup

    async def exercise() -> None:
        old = RequestPatch.model_validate({"expected_revision": 1, "set": {"hard_constraints": []}})
        before = await travel.get_request(context)
        async with transaction(travel.database) as db:
            row = await repository.owned_request(db, context)
            assert row is not None
            row.request_details = {"lodging_budget": None}
            operations.save(
                db,
                context.session_id,
                "update_travel_request",
                operations.key(old),
                {"request": legacy_request(before), "changed_fields": [], "skipped_fields": []},
            )
        turn = await create_run(travel, context, "合成明确删除床型要求")
        result = await TravelToolExecutor(travel).execute(
            turn,
            "update_travel_request",
            {
                "expected_revision": 1,
                "set": {"hard_constraints": []},
                "remove_hard_constraints": ["床型：无要求"],
                "explicit_fields": ["hard_constraints"],
            },
        )
        assert result.code is None
        assert "床型：无要求" not in (await travel.get_request(turn)).hard_constraints
        assert (await travel.get_request(turn)).revision == 2

    runner.run(exercise())


def test_typed_room_choices_use_same_storage_and_keep_other_user_facts(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        turn = await create_run(travel, context, "合成明确房型要求")
        result = await TravelToolExecutor(travel).execute(
            turn,
            "update_travel_request",
            {
                "expected_revision": 1,
                "room_preferences": {"lodging": "private", "smoking": "nonsmoking", "bed": "any"},
                "explicit_fields": ["hard_constraints"],
            },
        )
        assert result.code is None
        current = await travel.get_request(turn)
        assert set(current.hard_constraints) == {"住宿：独立房间", "房型：禁烟", "床型：无要求"}
        assert result.data["room_preferences"] == {
            "lodging": "private",
            "smoking": "nonsmoking",
            "bed": "any",
        }
        invalid = await TravelToolExecutor(travel).execute(
            replace(turn, run_id=uuid4()),
            "update_travel_request",
            {
                "expected_revision": 2,
                "room_preferences": {"bed": "大床优先"},
                "explicit_fields": ["hard_constraints"],
            },
        )
        assert invalid.code == "validation"
        assert invalid.suggestion and "explicit_fields" in invalid.suggestion
        assert (await travel.get_request(turn)).revision == 2

    runner.run(exercise())


def test_current_draft_recovers_and_completes_only_its_pending_task(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    from tests.integration.test_plans import initial_draft, version_count

    runner, travel, context = travel_setup

    async def exercise() -> None:
        origin = await create_run(travel, context, "合成酒店与行程任务")
        draft = await initial_draft(travel, origin)
        assert (
            await TravelToolExecutor(travel).execute(
                origin,
                "update_conversation_state",
                {
                    "expected_revision": draft.request_revision,
                    "goals": ["hotel_comparison", "itinerary"],
                },
            )
        ).code is None
        await finish(travel, origin)
        resumed = await create_run(travel, context, "继续")
        state = await travel.business_context(resumed)
        pending = state["pending_draft"]
        assert isinstance(pending, dict) and pending["draft_id"] == str(draft.draft_id)
        result = await TravelToolExecutor(travel).execute(
            resumed,
            "present_travel_result",
            {"component": "itinerary", "draft_id": pending["draft_id"]},
        )
        assert result.code is None
        tasks = (await travel.business_context(resumed))["conversation"]
        assert isinstance(tasks, dict) and tasks["pending_tasks"] == ["hotel_comparison"]
        assert await version_count(travel, draft.plan_id) == 0
        assert (await travel.get_request(resumed)).revision == draft.request_revision

    runner.run(exercise())


def test_native_sdk_fourth_stop_is_business_blocked_not_provider_error(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
) -> None:
    """P74/R13：真实SDK连续三次提醒后第四次结束仍待办未完成，覆盖真实stop_hook_prevented。"""
    from tests.integration.sdk_helper import run_database_worker
    from tests.test_sdk_cli_offline import scripted_response

    runner, travel, context = travel_setup
    turn = runner.run(create_run(travel, context, "合成酒店比较任务"))
    saved = runner.run(
        TravelToolExecutor(travel).execute(
            turn,
            "update_conversation_state",
            {"expected_revision": 1, "goals": ["hotel_comparison"]},
        )
    )
    assert saved.code is None
    requests: list[bytes] = []

    def forward(body: bytes) -> tuple[int, bytes]:
        requests.append(body)
        return scripted_response(
            b'{"messages":[{"content":[{"type":"tool_result",'
            b'"content":"Synthetic unfinished answer"}]}]}'
        )

    result, guard = run_database_worker(
        travel, turn, tmp_path, forward, "继续合成任务", max_attempts=4
    )
    assert result["status"] == "error" and result["code"] == "blocked"
    assert result["reason"] == "conversation_incomplete" and not guard.failures
    assert len(requests) == 4  # 初次 + 三次提醒
    dialogue = runner.run(travel.business_context(turn))["conversation"]
    assert isinstance(dialogue, dict) and dialogue["pending_tasks"] == ["hotel_comparison"]


def test_live_hotel_location_question_survives_restart_and_queries_selected_location(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """P74/R04/R13：PG保存独立地点，宽区域零请求；短答恢复原目标。"""
    import httpx

    from backend.adapters.google_maps import GoogleMaps
    from backend.adapters.live_data import LiveData
    from backend.adapters.rakuten import Rakuten
    from backend.domain.external_data import GeoPoint
    from backend.domain.hotels import HotelOffer
    from backend.domain.travel_request import TravelRequest
    from backend.services.hotels import HotelService
    from tests.test_external_data import _CountingUsage

    runner, travel, context = travel_setup

    async def exercise() -> None:
        calls: list[str] = []
        usage = _CountingUsage({})

        class Google(GoogleMaps):
            async def geocode(self, city: str) -> GeoPoint:
                calls.append(city)
                return GeoPoint(name=city, latitude=26, longitude=127)

        class Hotels(Rakuten):
            async def search(
                self,
                request: TravelRequest,
                point: GeoPoint,
                *,
                hotel_id: str | None = None,
                rate_id: str | None = None,
                limit: int = 4,
            ) -> tuple[HotelOffer, ...]:
                assert request.city == "冲绳" and request.hotel_search_location == "那霸"
                assert point.name == "那霸" and request.lodging_budget is None
                assert request.child_ages == () and request.rooms == 1
                return ()

        def never(request: httpx.Request) -> httpx.Response:
            pytest.fail("P74合成供应商不能连接真实HTTP")

        async with httpx.AsyncClient(transport=httpx.MockTransport(never)) as http:
            live = LiveData(
                Google("test", http, usage),
                Hotels("test", "test", "", "", http, usage),
                usage,
                http,
                {},
            )
            travel.live = live
            changed = await travel.patch_request(
                context,
                RequestPatch.model_validate(
                    {
                        "expected_revision": 1,
                        "set": {
                            "city": "冲绳",
                            "rooms": 1,
                            "budget": "50000",
                            "start_date": "2026-10-11",
                            "end_date": "2026-10-12",
                        },
                    }
                ),
            )
            revision = changed.request.revision
            turn = await create_run(travel, context, "合成宽区域酒店比较任务")
            tool = TravelToolExecutor(travel)
            saved = await tool.execute(
                turn,
                "update_conversation_state",
                {
                    "expected_revision": revision,
                    "goals": ["hotel_comparison"],
                    "awaiting_field": "hotel_search_location",
                },
            )
            assert saved.code is None
            blocked = await tool.execute(
                turn, "search_hotel_offers", {"expected_revision": revision}
            )
            assert (
                blocked.code == "validation" and "hotel_search_location_required" in blocked.detail
            )
            assert calls == [] and usage.calls == 0
            await finish(travel, turn)
            restored = TravelService(travel.database, live)
            state = (await restored.business_context(context))["conversation"]
            assert isinstance(state, dict) and state["awaiting_field"] == "hotel_search_location"
            assert state["ready_tasks"] == [] and state["missing_fields"] == [
                "hotel_search_location"
            ]
            answer = await create_run(restored, context, "合成地点短答")
            executor = TravelToolExecutor(restored)
            updated = await executor.execute(
                answer,
                "update_travel_request",
                {
                    "expected_revision": revision,
                    "set": {"hotel_search_location": "那霸"},
                    "explicit_fields": ["hotel_search_location"],
                },
            )
            assert updated.code is None and "住宿查询地点" in str(updated.data)
            request = await restored.get_request(answer)
            assert request.city == "冲绳" and request.hotel_search_location == "那霸"
            assert request.revision == revision + 1 and request.lodging_budget is None
            assert (await restored.get_request_view(answer)).field_sources[
                "hotel_search_location"
            ] == "conversation"
            ready = (await restored.business_context(answer))["conversation"]
            assert isinstance(ready, dict) and ready["ready_tasks"] == ["hotel_comparison"]
            assert await HotelService(restored).search(answer, request.revision) == ()
            assert calls == ["那霸"]
            query = await executor.execute(
                answer, "search_hotel_offers", {"expected_revision": request.revision}
            )
            assert query.code is None and query.empty
            state = (await restored.business_context(answer))["conversation"]
            assert isinstance(state, dict) and state["pending_tasks"] == []
            again = await restored.patch_request(
                answer,
                RequestPatch.model_validate(
                    {
                        "expected_revision": request.revision,
                        "set": {"hotel_search_location": "那霸"},
                    }
                ),
            )
            assert again.request.revision == request.revision and not again.changed_fields
            moved = await restored.patch_request(
                answer,
                RequestPatch.model_validate(
                    {"expected_revision": request.revision, "set": {"city": "札幌"}}
                ),
            )
            assert moved.request.hotel_search_location is None
            assert moved.field_sources["hotel_search_location"] == "none"

    runner.run(exercise())


def test_hotel_location_source_cas_and_legacy_storage_remain_safe(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """P74/R04：手填优先、显式更新、CAS、旧形状和旧writer目的地绑定。"""
    from backend.persistence.models import TravelRequestRow
    from backend.services.common import ServiceError
    from tests.fixtures.legacy_travel_request_v1 import TravelRequest as LegacyRequest

    runner, travel, context = travel_setup

    async def exercise() -> None:
        saved = await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {"expected_revision": 1, "set": {"city": "冲绳", "hotel_search_location": "那霸"}}
            ),
        )
        executor = TravelToolExecutor(travel)
        skipped = await executor.execute(
            context,
            "update_travel_request",
            {"expected_revision": 2, "set": {"hotel_search_location": "北谷"}},
        )
        assert skipped.code is None and skipped.data["skipped_fields"] == ("hotel_search_location",)
        assert (await travel.get_request(context)) == saved.request
        explicit = await executor.execute(
            context,
            "update_travel_request",
            {
                "expected_revision": 2,
                "set": {"hotel_search_location": "北谷"},
                "explicit_fields": ["hotel_search_location"],
            },
        )
        assert explicit.code is None
        current = await TravelService(travel.database).get_request(context)
        assert (
            current.city == "冲绳"
            and current.hotel_search_location == "北谷"
            and current.revision == 3
        )
        with pytest.raises(ServiceError) as conflict:
            await travel.patch_request(
                context,
                RequestPatch.model_validate(
                    {"expected_revision": 2, "set": {"hotel_search_location": "那霸"}}
                ),
            )
        assert conflict.value.code == "conflict"
        async with transaction(travel.database) as db:
            row = await db.get(TravelRequestRow, context.session_id)
            assert row is not None and row.request_details is not None
            assert "hotel_search_location" not in row.conditions
            assert row.request_details["hotel_search_location"] == "北谷"
            assert (
                LegacyRequest.model_validate({**row.conditions, "revision": row.revision}).city
                == "冲绳"
            )
            # 旧writer不更新details，不能把冲绳的住宿地点带入札幌。
            row.conditions = {**row.conditions, "city": "札幌"}
            row.revision = 4
        restored = await TravelService(travel.database).get_request(context)
        assert restored.city == "札幌" and restored.hotel_search_location is None
        assert (await travel.get_request_view(context)).field_sources[
            "hotel_search_location"
        ] == "none"

    runner.run(exercise())


@pytest.mark.parametrize("round_trip", [False, True])
def test_old_writer_revision_cannot_resurrect_untrusted_hotel_location(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    round_trip: bool,
) -> None:
    """P75/R04：旧writer无法维持地点完整性，往返city不能恢复失效事实。"""
    from backend.persistence.models import TravelRequestRow

    runner, travel, context = travel_setup

    async def exercise() -> None:
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {"expected_revision": 1, "set": {"city": "冲绳", "hotel_search_location": "那霸"}}
            ),
        )
        async with transaction(travel.database) as db:
            row = await db.get(TravelRequestRow, context.session_id)
            assert row is not None
            row.conditions = (
                {**row.conditions, "city": "札幌"}
                if round_trip
                else {**row.conditions, "budget": "60000"}
            )
            row.revision = 3
        if round_trip:
            async with transaction(travel.database) as db:
                row = await db.get(TravelRequestRow, context.session_id)
                assert row is not None
                row.conditions = {**row.conditions, "city": "冲绳"}
                row.revision = 4
        restored = await TravelService(travel.database).get_request(context)
        assert restored.city == "冲绳" and restored.hotel_search_location is None
        # 来源-only写入会刷新source_revision，但不能重新认证旧住宿地点。
        metadata = await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {"expected_revision": restored.revision, "set": {"adults": restored.adults}}
            ),
        )
        assert (
            not metadata.changed_fields
            and (await travel.get_request(context)).hotel_search_location is None
        )
        async with transaction(travel.database) as db:
            row = await db.get(TravelRequestRow, context.session_id)
            assert row is not None and row.request_details is not None
            assert (
                row.request_details["hotel_search_location"] == "那霸"
            )  # 原文保留，但不冒充当前有效值。

    runner.run(exercise())

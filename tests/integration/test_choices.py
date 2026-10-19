"""真实PG：结构化点选与消息同事务，保护归属、版本和重放。"""

import asyncio
from uuid import UUID, uuid4

import pytest

from backend.domain.choices import TRANSPORT_PACE_GROUPS, ChoiceCard
from backend.domain.conversation import ConversationStateInput
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeOutcome
from backend.domain.travel_request import RequestPatch, pace_of
from backend.persistence import runs
from backend.providers.claude_agent.database_tools import DatabaseTools
from backend.services.choices import ChoiceService
from backend.services.common import ServiceError, transaction
from backend.services.runs import MessageInput, RunService
from backend.services.travel import TravelService
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from tests.errors import assert_error
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration

# 合并选择卡里的行程信息都已知（房型偏好沿用夹具的“无要求”；文字不含数字，不触发旧的时间确认题）。
ASKED_HARD = (
    "住宿：无要求",
    "房型：无要求",
    "床型：无要求",
    "第一天抵达：下午",
    "最后一天离开：傍晚",
)
ASKED_SOFT = ("平时起床：早", "晚上结束：晚", "同行：朋友")


def test_cancelling_the_task_retires_its_unanswered_details_card(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        changed = await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {
                        "transport": "transit",
                        "lodging_budget_unlimited": True,
                        "hard_constraints": ["节奏：标准", *ASKED_HARD],
                        "soft_constraints": list(ASKED_SOFT),
                    },
                }
            ),
        )
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, context.user_id, context.session_id, uuid4(), "先确认", "offline"
            )
            active = RunContext(context.user_id, context.session_id, row.id)
        await travel.update_conversation_state(
            active,
            ConversationStateInput(
                expected_revision=changed.request.revision, goals=("itinerary",)
            ),
        )
        card = await ChoiceService(travel).create(
            active, "form", changed.request.revision, TRANSPORT_PACE_GROUPS
        )
        await travel.update_conversation_state(
            active, ConversationStateInput(expected_revision=changed.request.revision, cancel=True)
        )
        assert not (await travel.business_context(active)).get("awaiting_travel_details")
        restored = await ChoiceService(travel).get(
            context.user_id, context.session_id, card.choice_id
        )
        assert restored.stale and restored.answered_option_id is None
        await travel.update_conversation_state(
            active,
            ConversationStateInput(
                expected_revision=changed.request.revision, goals=("itinerary",)
            ),
        )
        tools = DatabaseTools(asyncio.get_running_loop(), travel.database)
        assert await tools.continuation_reason(active, 1) is not None

    runner.run(exercise())


def test_combined_card_stops_automatic_planning_until_explicit_confirmation(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        changed = await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {
                        "transport": "transit",
                        "lodging_budget_unlimited": True,
                        "hard_constraints": ["节奏：标准", *ASKED_HARD],
                        "soft_constraints": list(ASKED_SOFT),
                    },
                }
            ),
        )
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, context.user_id, context.session_id, uuid4(), "确认后规划", "offline"
            )
            active = RunContext(context.user_id, context.session_id, row.id)
        await travel.update_conversation_state(
            active,
            ConversationStateInput(
                expected_revision=changed.request.revision, goals=("itinerary",)
            ),
        )
        tools = DatabaseTools(asyncio.get_running_loop(), travel.database)
        assert await tools.continuation_reason(active, 1) is not None
        card = await ChoiceService(travel).create(
            active, "form", changed.request.revision, TRANSPORT_PACE_GROUPS
        )
        assert card.form and all(group.kind != "times" for group in card.form.groups)
        assert await tools.continuation_reason(active, 1) is None
        with pytest.raises(ServiceError) as failed:
            await travel.update_conversation_state(
                active,
                ConversationStateInput(
                    expected_revision=changed.request.revision, confirm_details=True
                ),
            )
        assert_error(failed, 422, "validation")
        unrelated = await travel.patch_request(
            active,
            RequestPatch.model_validate(
                {"expected_revision": changed.request.revision, "set": {"interests": ["甜点"]}}
            ),
        )
        assert await tools.continuation_reason(active, 1) is None
        for name in ("estimate_routes", "validate_itinerary", "stage_plan_change"):
            result = await tools.execute(active, name, {})
            assert result.code == "validation" and result.detail == ("conversation_incomplete",)
        assert tools.executor.calls == 0
        async with transaction(travel.database) as db:
            await runs.finish(db, active, RuntimeOutcome(text="请选择"))
            row = await runs.create(
                db,
                context.user_id,
                context.session_id,
                uuid4(),
                "交通公共交通，节奏标准，继续",
                "offline",
            )
            next_turn = RunContext(context.user_id, context.session_id, row.id)
        # 无关的新消息不绕过确认；明确文字回答经现有状态工具确认后可继续。
        assert await tools.continuation_reason(next_turn, 1) is None
        await travel.update_conversation_state(
            next_turn,
            ConversationStateInput(
                expected_revision=unrelated.request.revision, confirm_details=True
            ),
        )
        assert await tools.continuation_reason(next_turn, 1) is not None

    runner.run(exercise())


@pytest.mark.parametrize("correct", [True, False])
def test_combined_details_are_saved_once_with_the_message_and_restored(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], correct: bool
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {
                        "transport": "transit",
                        "hard_constraints": [
                            "住宿：无要求",
                            "2026-11-10 09:00抵达；2026-11-12 22:00离开",
                        ],
                    },
                }
            ),
        )
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, context.user_id, context.session_id, uuid4(), "规划旅行", "offline"
            )
            source = RunContext(context.user_id, context.session_id, row.id)
        card = await ChoiceService(travel).create(source, "form", 2, TRANSPORT_PACE_GROUPS)
        assert card.kind == "form" and card.form
        groups = {group.key: group for group in card.form.groups}
        assert groups["transport"].selected == ("transit",) and groups["pace"].selected == ()
        assert groups["times"].shown == ("2026-11-10 09:00抵达；2026-11-12 22:00离开",)
        assert (await travel.read_request(context)).revision == 2
        async with transaction(travel.database) as db:
            await runs.finish(db, source, RuntimeOutcome(text="请一次确认"))
        message = MessageInput.model_validate(
            {
                "client_message_id": str(uuid4()),
                "text": "确认交通、节奏与时间",
                "expected_revision": 2,
                "selection": {
                    "choice_id": str(card.choice_id),
                    "option_id": "confirm",
                    "answers": {
                        "transport": ["taxi"],
                        "pace": ["relaxed"],
                        "times": ["yes" if correct else "no"],
                        **(
                            {}
                            if correct
                            else {"times_corrected": ["2026-11-10 10:00抵达；2026-11-12 21:00离开"]}
                        ),
                    },
                },
            }
        )
        service = RunService(travel.database)
        first, replay = await asyncio.gather(
            service.submit(context.user_id, context.session_id, message),
            service.submit(context.user_id, context.session_id, message),
        )
        assert first.run_id == replay.run_id
        await asyncio.gather(*tuple(service.tasks.values()))
        result = await travel.read_request(context)
        assert result.revision == 3 and result.transport == "taxi" and pace_of(result) == "慢节奏"
        expected = (
            "2026-11-10 09:00抵达；2026-11-12 22:00离开"
            if correct
            else "2026-11-10 10:00抵达；2026-11-12 21:00离开"
        )
        assert set(result.hard_constraints) == {"住宿：无要求", "节奏：慢节奏", expected}
        restored = await ChoiceService(TravelService(travel.database)).get(
            context.user_id, context.session_id, card.choice_id
        )
        assert restored.answered_option_id == "confirm"
        assert restored.form
        restored_groups = {group.key: group for group in restored.form.groups}
        assert restored_groups["transport"].selected == ("taxi",)
        assert restored_groups["times"].shown == (expected,)
        replay_after_restart = await RunService(travel.database).submit(
            context.user_id, context.session_id, message
        )
        assert replay_after_restart.run_id == first.run_id
        tampered = message.model_dump(mode="json")
        tampered["selection"]["answers"]["transport"] = ["walk"]
        with pytest.raises(ServiceError) as changed_replay:
            await service.submit(
                context.user_id, context.session_id, MessageInput.model_validate(tampered)
            )
        assert changed_replay.value.status == 409
        await service.close()

    runner.run(exercise())


@pytest.mark.parametrize(
    "failure",
    [
        "empty",
        "empty_correction",
        "unknown_option",
        "two_for_single",
        "stale",
        "owner",
    ],
)
def test_invalid_combined_details_do_not_write_a_message_or_change_conditions(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], failure: str
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {
                        "hard_constraints": ["2026-11-10 09:00抵达；2026-11-12 22:00离开"],
                    },
                }
            ),
        )
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, context.user_id, context.session_id, uuid4(), "规划旅行", "offline"
            )
            source = RunContext(context.user_id, context.session_id, row.id)
        card = await ChoiceService(travel).create(source, "form", 2, TRANSPORT_PACE_GROUPS)
        async with transaction(travel.database) as db:
            await runs.finish(db, source, RuntimeOutcome(text="请选择"))
        if failure == "stale":
            await travel.patch_request(
                context,
                RequestPatch.model_validate(
                    {"expected_revision": 2, "set": {"interests": ["甜点"]}}
                ),
            )
        before = await travel.read_request(context)
        answers: dict[str, list[str]] = {
            "transport": ["walk"],
            "pace": ["standard"],
            "times": ["yes"],
        }
        if failure == "empty":
            answers.clear()
        if failure == "empty_correction":
            answers.update(times=["no"], times_corrected=["   "])
        if failure == "unknown_option":
            answers["pace"] = ["invented"]
        if failure == "two_for_single":
            answers["transport"] = ["walk", "taxi"]
        client_id = uuid4()
        service = RunService(travel.database)
        with pytest.raises((ValueError, ServiceError)):
            await service.submit(
                uuid4() if failure == "owner" else context.user_id,
                context.session_id,
                MessageInput.model_validate(
                    {
                        "client_message_id": str(client_id),
                        "text": "确认",
                        "expected_revision": 2,
                        "selection": {
                            "choice_id": str(card.choice_id),
                            "option_id": "confirm",
                            "answers": answers,
                        },
                    }
                ),
            )
        assert await travel.read_request(context) == before
        async with transaction(travel.database) as db:
            assert await runs.by_message(db, context.session_id, client_id) is None
        assert not service.tasks
        await service.close()

    runner.run(exercise())


def test_direct_pace_request_without_itinerary_task_creates_card_without_changing_conditions(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, original = travel_setup

    async def exercise() -> None:
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, original.user_id, original.session_id, uuid4(), "给我旅行节奏选择卡", "offline"
            )
            context = RunContext(original.user_id, original.session_id, row.id)
        before = await travel.read_request(context)
        result = await TravelToolExecutor(travel).execute(
            context,
            "present_travel_result",
            {"component": "choice", "kind": "pace", "expected_revision": before.revision},
        )
        assert result.code is None
        options = result.data["options"]
        assert isinstance(options, list) and len(options) == 3
        assert await travel.read_request(context) == before
        snapshot = await travel.business_context(context)
        state = snapshot["conversation"]
        assert isinstance(state, dict) and state["pending_tasks"] == []

    runner.run(exercise())


def test_goals_automatically_emit_one_combined_card_and_explicit_form_supersedes_it(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, original = travel_setup

    async def exercise() -> None:
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, original.user_id, original.session_id, uuid4(), "合成问题", "offline"
            )
            context = RunContext(original.user_id, original.session_id, row.id)
        events: list[RuntimeEvent] = []
        executor = TravelToolExecutor(travel)
        arguments = {"expected_revision": 1, "goals": ["itinerary"], "awaiting_field": "transport"}
        definition = next(d for d in DEFINITIONS if d.name == "update_conversation_state")
        result = await execute_observed(
            executor, context, "update_conversation_state", arguments, events.append,
            definition=definition,
        )  # fmt: skip
        assert result.code is None
        presentations = [event.presentation for event in events if event.kind == "presentation"]
        assert len(presentations) == 1 and presentations[0]
        data = presentations[0]["data"]
        assert isinstance(data, dict) and data["component"] == "choice"
        assert data["form"]["purpose"] == "trip_ask"
        # 同一状态再记录一次：复用同一张未答卡，不重复展示
        events.clear()
        again = await execute_observed(
            executor, context, "update_conversation_state", arguments, events.append,
            definition=definition,
        )  # fmt: skip
        assert again.code is None and "choice" not in again.data
        assert again.data["awaiting_trip_details"] is True
        assert not [event for event in events if event.kind == "presentation"]
        # 模型显式出另一张表单：取代合并卡
        explicit = await executor.execute(
            context,
            "present_form",
            {"expected_revision": 1, "groups": [{"key": "transport", "label": "交通方式"}]},
        )
        assert explicit.code is None and explicit.data["choice_id"] != data["choice_id"]
        old = await ChoiceService(travel).get(
            context.user_id, context.session_id, UUID(str(data["choice_id"]))
        )
        assert old.stale and old.answered_option_id is None
        assert (await travel.read_request(context)).revision == 1

    runner.run(exercise())


async def source_card(travel: TravelService, original: RunContext) -> tuple[RunContext, ChoiceCard]:
    async with transaction(travel.database) as db:
        row = await runs.create(
            db, original.user_id, original.session_id, uuid4(), "合成节奏问题", "offline"
        )
        context = RunContext(original.user_id, original.session_id, row.id)
    await travel.update_conversation_state(
        context,
        ConversationStateInput(
            expected_revision=1, goals=("itinerary",), awaiting_field="transport"
        ),
    )
    card = await ChoiceService(travel).create(context, "pace", 1)
    async with transaction(travel.database) as db:
        await runs.finish(db, context, RuntimeOutcome(text="请选择旅行节奏"))
    return context, card


def test_choice_submission_preserves_conditions_and_survives_restart(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        _, card = await source_card(travel, context)
        service = RunService(travel.database)
        message = MessageInput.model_validate(
            {
                "client_message_id": str(uuid4()),
                "text": "选择比较轻松",
                "expected_revision": 1,
                "selection": {"choice_id": str(card.choice_id), "option_id": "relaxed"},
            }
        )
        first, second = await asyncio.gather(
            service.submit(context.user_id, context.session_id, message),
            service.submit(context.user_id, context.session_id, message),
        )
        assert first.run_id == second.run_id
        await asyncio.gather(*tuple(service.tasks.values()))
        request = await travel.read_request(context)
        assert pace_of(request) == "慢节奏" and request.revision == 2
        assert "住宿：无要求" in request.hard_constraints
        assert (await travel.get_request_view(context)).field_sources[
            "hard_constraints"
        ] == "user_form"
        echoed = await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": request.revision,
                    "set": {"hard_constraints": list(request.hard_constraints)},
                }
            ),
            source="conversation",
            explicit_fields=("hard_constraints",),
        )
        assert not echoed.changed_fields and echoed.field_sources["hard_constraints"] == "user_form"
        restored = await ChoiceService(TravelService(travel.database)).get(
            context.user_id, context.session_id, card.choice_id
        )
        assert restored.answered_option_id == "relaxed"
        replay = await RunService(travel.database).submit(
            context.user_id, context.session_id, message
        )
        assert replay.run_id == first.run_id
        with pytest.raises(ServiceError) as duplicate:
            await service.submit(
                context.user_id,
                context.session_id,
                message.model_copy(update={"client_message_id": uuid4()}),
            )
        assert duplicate.value.status == 409
        await service.close()

    runner.run(exercise())


@pytest.mark.parametrize("failure", ["option", "revision", "owner"])
def test_invalid_choice_cannot_modify_request(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], failure: str
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        _, card = await source_card(travel, context)
        if failure == "revision":
            await travel.patch_request(
                context,
                RequestPatch.model_validate(
                    {"expected_revision": 1, "set": {"interests": ["合成甜点"]}}
                ),
            )
        before = await travel.read_request(context)
        service = RunService(travel.database)
        message = MessageInput.model_validate(
            {
                "client_message_id": str(uuid4()),
                "text": "选择标准",
                "expected_revision": 1,
                "selection": {
                    "choice_id": str(card.choice_id),
                    "option_id": "invented" if failure == "option" else "standard",
                },
            }
        )
        with pytest.raises(ServiceError) as rejected:
            await service.submit(
                uuid4() if failure == "owner" else context.user_id, context.session_id, message
            )
        assert rejected.value.status == {"option": 422, "revision": 409, "owner": 404}[failure]
        assert await travel.read_request(context) == before
        assert not service.tasks
        await service.close()

    runner.run(exercise())


def test_explicit_card_can_change_existing_hard_and_soft_pace(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, original = travel_setup

    async def exercise() -> None:
        request = await travel.read_request(original)
        await travel.patch_request(
            original,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {
                        "hard_constraints": [*request.hard_constraints, "节奏：标准"],
                        "soft_constraints": ["甜点", "佛系"],
                    },
                }
            ),
        )
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, original.user_id, original.session_id, uuid4(), "想修改节奏", "offline"
            )
            context = RunContext(original.user_id, original.session_id, row.id)
        await travel.update_conversation_state(
            context, ConversationStateInput(expected_revision=2, goals=("itinerary",))
        )
        card = await ChoiceService(travel).create(context, "pace", 2)
        assert pace_of(await travel.read_request(context)) == "标准"
        async with transaction(travel.database) as db:
            await runs.finish(db, context, RuntimeOutcome(text="请选择新的节奏"))
        service = RunService(travel.database)
        await service.submit(
            original.user_id,
            original.session_id,
            MessageInput.model_validate(
                {
                    "client_message_id": str(uuid4()),
                    "text": "选择特种兵",
                    "expected_revision": 2,
                    "selection": {"choice_id": str(card.choice_id), "option_id": "intensive"},
                }
            ),
        )
        await asyncio.gather(*tuple(service.tasks.values()))
        updated = await travel.read_request(original)
        assert pace_of(updated) == "特种兵"
        assert updated.hard_constraints == (*request.hard_constraints, "节奏：特种兵")
        assert updated.soft_constraints == ("甜点",)
        await service.close()

    runner.run(exercise())


CONFIRM = {"option_id": "confirm", "label": "确认并继续", "value": "confirm"}


async def run_context(travel: TravelService, original: RunContext, text: str) -> RunContext:
    async with transaction(travel.database) as db:
        row = await runs.create(db, original.user_id, original.session_id, uuid4(), text, "offline")
        return RunContext(original.user_id, original.session_id, row.id)


def test_extra_group_answers_land_only_in_constraint_text_and_replace_on_reask(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, original = travel_setup
    group = {
        "key": "companion",
        "label": "同行者",
        "options": [{"option_id": "a", "label": "带孩子"}, {"option_id": "b", "label": "朋友"}],
    }

    async def ask(answer: str, revision: int) -> None:
        source = await run_context(travel, original, "追问")
        result = await TravelToolExecutor(travel).execute(
            source,
            "present_form",
            {"expected_revision": revision, "groups": [group, {"key": "pace", "label": "节奏"}]},
        )
        assert result.code is None
        async with transaction(travel.database) as db:
            await runs.finish(db, source, RuntimeOutcome(text="请选择"))
        service = RunService(travel.database)
        await service.submit(
            original.user_id,
            original.session_id,
            MessageInput.model_validate(
                {
                    "client_message_id": str(uuid4()),
                    "text": "确认",
                    "expected_revision": revision,
                    "selection": {
                        "choice_id": str(result.data["choice_id"]),
                        "option_id": "confirm",
                        "answers": {"companion": [answer], "pace": ["standard"]},
                    },
                }
            ),
        )
        await asyncio.gather(*service.tasks.values())
        await service.close()

    async def exercise() -> None:
        before = await travel.read_request(original)
        await ask("a", before.revision)
        first = await travel.read_request(original)
        assert "同行者：带孩子" in first.hard_constraints and first.transport == before.transport
        await ask("b", first.revision)
        second = await travel.read_request(original)
        assert [t for t in second.hard_constraints if t.startswith("同行者")] == ["同行者：朋友"]

    runner.run(exercise())

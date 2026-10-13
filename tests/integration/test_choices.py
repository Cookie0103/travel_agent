"""真实PG：结构化点选与消息同事务，保护归属、版本和重放。"""

import asyncio
from uuid import uuid4

import pytest

from backend.domain.choices import ChoiceCard
from backend.domain.conversation import ConversationStateInput
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeOutcome
from backend.domain.travel_request import RequestPatch, pace_of
from backend.persistence import runs
from backend.services.choices import ChoiceService
from backend.services.common import ServiceError, transaction
from backend.services.runs import MessageInput, RunService
from backend.services.travel import TravelService
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


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
        before = await travel.get_request(context)
        result = await TravelToolExecutor(travel).execute(
            context,
            "present_travel_result",
            {"component": "choice", "kind": "pace", "expected_revision": before.revision},
        )
        assert result.code is None
        options = result.data["options"]
        assert isinstance(options, list) and len(options) == 3
        assert await travel.get_request(context) == before
        snapshot = await travel.business_context(context)
        state = snapshot["conversation"]
        assert isinstance(state, dict) and state["pending_tasks"] == []

    runner.run(exercise())


def test_awaiting_pace_automatically_emits_card_and_explicit_presentation_reuses_it(
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
        result = await execute_observed(
            executor,
            context,
            "update_conversation_state",
            {"expected_revision": 1, "goals": ["itinerary"], "awaiting_field": "pace"},
            events.append,
            definition=next(d for d in DEFINITIONS if d.name == "update_conversation_state"),
        )
        assert result.code is None
        presentations = [event.presentation for event in events if event.kind == "presentation"]
        assert len(presentations) == 1 and presentations[0]
        data = presentations[0]["data"]
        assert isinstance(data, dict) and data["component"] == "choice"
        repeated = await executor.execute(
            context,
            "present_travel_result",
            {"component": "choice", "kind": "pace", "expected_revision": 1},
        )
        assert repeated.code is None and repeated.data["choice_id"] == data["choice_id"]
        assert (await travel.get_request(context)).revision == 1

    runner.run(exercise())


async def source_card(travel: TravelService, original: RunContext) -> tuple[RunContext, ChoiceCard]:
    async with transaction(travel.database) as db:
        row = await runs.create(
            db, original.user_id, original.session_id, uuid4(), "合成节奏问题", "offline"
        )
        context = RunContext(original.user_id, original.session_id, row.id)
    await travel.update_conversation_state(
        context,
        ConversationStateInput(expected_revision=1, goals=("itinerary",), awaiting_field="pace"),
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
        request = await travel.get_request(context)
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
        before = await travel.get_request(context)
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
        assert await travel.get_request(context) == before
        assert not service.tasks
        await service.close()

    runner.run(exercise())


def test_explicit_card_can_change_existing_hard_and_soft_pace(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, original = travel_setup

    async def exercise() -> None:
        request = await travel.get_request(original)
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
        assert pace_of(await travel.get_request(context)) == "标准"
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
        updated = await travel.get_request(original)
        assert pace_of(updated) == "特种兵"
        assert updated.hard_constraints == (*request.hard_constraints, "节奏：特种兵")
        assert updated.soft_constraints == ("甜点",)
        await service.close()

    runner.run(exercise())

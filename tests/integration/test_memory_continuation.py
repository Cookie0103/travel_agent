"""确认只续接安全待办，遗忘胜出仍在运行的旧提议。"""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.domain.memory import MemoryProposal
from backend.domain.preferences import PreferencePatch, PreferenceVersion
from backend.persistence import runs
from backend.persistence.models import ChoiceCardRow
from backend.services.common import ServiceError, transaction
from backend.services.memory import MemoryService
from backend.services.preferences import PreferenceService
from backend.services.runs import MessageInput, RunService
from backend.services.travel import TravelService
from backend.tools.travel import TravelToolExecutor
from tests.fakes import FakeRuntime
from tests.integration.test_memory import click, proposal
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def test_repeated_empty_forget_keeps_public_revision_but_invalidates_old_checkpoint(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, original = travel_setup

    async def exercise() -> None:
        preferences = PreferenceService(travel.database)
        first = await preferences.change(original.user_id, PreferenceVersion(expected_revision=0))
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, original.user_id, original.session_id, uuid4(), "新的私有偏好原话", "offline"
            )
            source = RunContext(original.user_id, original.session_id, row.id)
        memory = MemoryService(travel.database)
        assert await memory.checkpoint_allowed(original, source.run_id)
        second = await preferences.change(
            original.user_id, PreferenceVersion(expected_revision=first.revision)
        )
        assert first == second
        assert not await memory.checkpoint_allowed(original, source.run_id)

    runner.run(exercise())


@pytest.mark.parametrize("option", ("remember", "trip", "reject"))
def test_memory_confirmation_keeps_tasks_but_does_not_restore_old_goal_text(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], option: str
) -> None:
    runner, travel, original = travel_setup

    async def exercise() -> None:
        async with transaction(travel.database) as db:
            row = await runs.create(
                db,
                original.user_id,
                original.session_id,
                uuid4(),
                "我喜欢特种兵；原任务中的私人资料不再注入",
                "offline",
            )
            context = RunContext(original.user_id, original.session_id, row.id)
        result = await TravelToolExecutor(travel).execute(
            context,
            "update_conversation_state",
            {
                "expected_revision": 1,
                "goals": ["hotel_comparison", "itinerary"],
                "awaiting_field": "transport",
            },
        )
        assert result.code is None
        cards = await MemoryService(travel.database).propose(
            context,
            MemoryProposal.model_validate(
                {
                    "ops": [
                        {"op": "ADD", "key": "interest", "value": "特种兵", "quote": "我喜欢特种兵"}
                    ]
                }
            ),
        )
        async with transaction(travel.database) as db:
            await runs.finish(db, context, RuntimeOutcome(text="请选择", sdk_session_id="fixture"))
        await click(travel, context, cards[0], option)
        state = (await travel.business_context(original))["conversation"]
        assert isinstance(state, dict)
        assert state["pending_tasks"] == ["hotel_comparison", "itinerary"]
        assert state["awaiting_field"] == "transport"
        assert state["goal_prompt"] is None
        # 下一轮追问与重复原目标，都必须保留已确认的安全待办证明。
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, original.user_id, original.session_id, uuid4(), "继续原任务", "offline"
            )
            followup = RunContext(original.user_id, original.session_id, row.id)
        for goals in (None, ["hotel_comparison", "itinerary"]):
            result = await TravelToolExecutor(travel).execute(
                followup,
                "update_conversation_state",
                {"expected_revision": 1, "goals": goals, "awaiting_field": "transport"},
            )
            assert result.code is None
            state = (await travel.business_context(followup))["conversation"]
            assert isinstance(state, dict)
            assert state["pending_tasks"] == ["hotel_comparison", "itinerary"]
            assert state["awaiting_field"] == "transport"
            assert state["goal_prompt"] is None
        await PreferenceService(travel.database).change(
            original.user_id, PreferenceVersion(expected_revision=1)
        )
        state = (await travel.business_context(original))["conversation"]
        assert isinstance(state, dict)
        assert state["pending_tasks"] == [] and state["goal_prompt"] is None

    runner.run(exercise())


@pytest.mark.parametrize("single", (False, True))
def test_forget_wins_late_running_proposal_but_allows_new_explicit_input(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], single: bool
) -> None:
    runner, travel, original = travel_setup

    async def exercise() -> None:
        memory = MemoryService(travel.database)
        version = 0
        target = None
        if single:
            await PreferenceService(travel.database).change(
                original.user_id,
                PreferencePatch.model_validate(
                    {"expected_revision": 0, "set": {"interests": ["寺庙"]}}
                ),
            )
            target = (await memory.facts(original.user_id))[0]
            version = 1
        started, release = asyncio.Event(), asyncio.Event()
        refusals: list[int] = []

        class Delayed(FakeRuntime):
            async def execute(
                self,
                context: RunContext,
                prompt: str,
                sdk_session_id: str | None,
                emit: EventSink,
                cancelled: asyncio.Event,
            ) -> RuntimeOutcome:
                started.set()
                await release.wait()
                try:
                    await memory.propose(
                        context,
                        MemoryProposal.model_validate(
                            {
                                "ops": [
                                    {"op": "ADD", "key": "pace", "value": "特种兵", "quote": prompt}
                                ]
                            }
                        ),
                    )
                except ServiceError as error:
                    refusals.append(error.status)
                return RuntimeOutcome(text="迟到提议已结束", sdk_session_id="fixture")

        service = RunService(travel.database, runtime_factory=lambda _: Delayed(RuntimeOutcome()))
        try:
            submitted = await service.submit(
                original.user_id,
                original.session_id,
                MessageInput(client_message_id=uuid4(), text="我长期喜欢特种兵旅行"),
            )
            await asyncio.wait_for(started.wait(), 2)
            if target:
                await memory.delete(
                    original.user_id, target.fact_id, PreferenceVersion(expected_revision=version)
                )
            else:
                await PreferenceService(travel.database).change(
                    original.user_id, PreferenceVersion(expected_revision=version)
                )
            release.set()
            await asyncio.gather(*tuple(service.tasks.values()))
            assert refusals == [409]
            assert all(
                f.value is None and not f.evidence_quote
                for f in await memory.facts(original.user_id, include_history=True)
            )
            async with transaction(travel.database) as db:
                assert (
                    await db.scalar(
                        select(ChoiceCardRow.id).where(
                            ChoiceCardRow.source_run_id == submitted.run_id
                        )
                    )
                    is None
                )
            _, cards = await proposal(
                travel,
                original,
                "现在重新告诉你，我长期喜欢特种兵",
                [{"op": "ADD", "key": "pace", "value": "特种兵", "quote": "我长期喜欢特种兵"}],
            )
            assert len(cards) == 1
        finally:
            release.set()
            await service.close()

    runner.run(exercise())

"""R2: runtime completion cannot claim a business commit; facts survive PostgreSQL reads."""

import asyncio
from uuid import uuid4

import pytest

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.services.history import HistoryService
from backend.services.runs import MessageInput, RunService
from backend.services.travel import TravelService
from backend.tools.contracts import ToolResult
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS
from tests.fakes import FakeRuntime
from tests.integration.test_plans import initial_draft, version_count
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


class StageRuntime(FakeRuntime):
    def __init__(self, results: tuple[ToolResult, ...]) -> None:
        super().__init__(RuntimeOutcome(text="已通过，已保存", sdk_session_id="synthetic"))
        self.results = results

    async def execute(
        self,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        definition = next(d for d in DEFINITIONS if d.name == "stage_plan_change")

        class ResultExecutor:
            def __init__(self, value: ToolResult) -> None:
                self.value = value

            async def execute(self, *args: object) -> ToolResult:
                return self.value

        for result in self.results:
            await execute_observed(
                ResultExecutor(result), context, definition.name, {}, emit, definition=definition
            )
        return self.outcome


def test_stage_failure_is_distinct_from_successful_runtime_and_history(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    runtime = StageRuntime(
        (ToolResult({}, code="conflict", detail=("service:409", "plan_exists")),)
    )
    service = RunService(travel.database, runtime_factory=lambda executor: runtime)

    async def exercise() -> None:
        run = await service.submit(
            context.user_id,
            context.session_id,
            MessageInput(client_message_id=uuid4(), text="生成"),
        )
        await asyncio.gather(*tuple(service.tasks.values()))
        current = await service.get(context.user_id, run.run_id)
        assert current.status == "completed" and current.answer == "已通过，已保存"
        result = getattr(current, "business_result", None)
        assert result is not None and result.kind == "stage_failed"
        assert result.code == "conflict" and result.reason == "plan_exists"
        history = await HistoryService(travel.database).runs(
            context.user_id, context.session_id, 20, None
        )
        assert history.items[0].business_result == result
        assert (
            await RunService(travel.database).get(context.user_id, run.run_id)
        ).business_result == result
        await service.close()

    runner.run(exercise())


@pytest.mark.parametrize("previous_finished", [False, True])
def test_interrupted_stage_result_is_unknown_even_after_an_earlier_result(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], previous_finished: bool
) -> None:
    from backend.domain.execution import BusinessResult, RuntimeEvent
    from backend.persistence import runs
    from backend.services.common import transaction

    runner, travel, context = travel_setup

    async def exercise() -> None:
        # A draft may commit before its observed result is durably recorded.
        draft = await initial_draft(travel, context)
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, context.user_id, context.session_id, uuid4(), "中断的暂存", "offline"
            )
            interrupted = RunContext(context.user_id, context.session_id, row.id)
            if previous_finished:
                await runs.append_event(
                    db,
                    RuntimeEvent(
                        interrupted,
                        "tool_finished",
                        tool_name="stage_plan_change",
                        business_result=BusinessResult(
                            "stage_failed", code="conflict", reason="plan_exists"
                        ),
                    ),
                )
            await runs.append_event(
                db,
                RuntimeEvent(
                    interrupted, "tool_started", tool_name="stage_plan_change", tool_call_id=uuid4()
                ),
            )
            await runs.recover(db, interrupted)
        current = await RunService(travel.database).get(context.user_id, row.id)
        assert current.status == "partial" and current.business_result is None
        page = await HistoryService(travel.database).runs(
            context.user_id, context.session_id, 20, None
        )
        assert page.items[0].business_result is None
        assert await version_count(travel, draft.plan_id) == 0

    runner.run(exercise())


@pytest.mark.parametrize("closed", [False, True])
def test_stage_without_presentation_uses_actual_report_and_confirmation(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], closed: bool
) -> None:
    from backend.services.common import ServiceError
    from backend.services.plans import PlanService

    runner, travel, context = travel_setup

    async def exercise() -> None:
        draft = await initial_draft(travel, context, closed=closed)
        service = RunService(
            travel.database,
            runtime_factory=lambda executor: StageRuntime((ToolResult(draft.summary()),)),
        )
        run = await service.submit(
            context.user_id,
            context.session_id,
            MessageInput(client_message_id=uuid4(), text="合成已暂存结果"),
        )
        await asyncio.gather(*tuple(service.tasks.values()))
        current = await service.get(context.user_id, run.run_id)
        assert current.presentations == ()
        result = getattr(current, "business_result", None)
        assert result is not None and result.kind == "draft_staged"
        assert result.validation_status == ("conflict" if closed else "partial")
        assert result.draft_id == draft.draft_id and await version_count(travel, draft.plan_id) == 0
        if closed:
            with pytest.raises(ServiceError):
                await PlanService(travel).confirm(context.user_id, draft.draft_id)
            assert await version_count(travel, draft.plan_id) == 0
        else:
            saved = await PlanService(travel).confirm(context.user_id, draft.draft_id)
            confirmed = (await service.get(context.user_id, run.run_id)).business_result
            assert (
                confirmed is not None
                and confirmed.kind == "confirmed"
                and confirmed.version == saved.version
            )
            assert confirmed.plan_id == saved.plan_id
            page = await HistoryService(travel.database).runs(
                context.user_id, context.session_id, 20, None
            )
            assert page.items[0].business_result == confirmed
            assert await version_count(travel, draft.plan_id) == 1
        await service.close()

    runner.run(exercise())


@pytest.mark.parametrize("last_failed", [False, True])
def test_last_stage_wins_even_when_earlier_draft_is_already_confirmed(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], last_failed: bool
) -> None:
    from backend.services.plans import PlanService

    runner, travel, context = travel_setup

    async def exercise() -> None:
        draft = await initial_draft(travel, context)
        staged = ToolResult(draft.summary())
        failed = ToolResult({}, code="validation", detail=("patch_invalid",))
        values = (staged, failed) if last_failed else (failed, staged)
        service = RunService(travel.database, runtime_factory=lambda executor: StageRuntime(values))
        run = await service.submit(
            context.user_id,
            context.session_id,
            MessageInput(client_message_id=uuid4(), text="多次修复"),
        )
        await asyncio.gather(*tuple(service.tasks.values()))
        await PlanService(travel).confirm(context.user_id, draft.draft_id)
        result = (await service.get(context.user_id, run.run_id)).business_result
        assert result is not None and result.kind == (
            "stage_failed" if last_failed else "confirmed"
        )
        if last_failed:
            assert result.reason == "patch_invalid"
        assert await version_count(travel, draft.plan_id) == 1
        await service.close()

    runner.run(exercise())


def test_legacy_success_cannot_borrow_confirmed_draft_from_another_turn(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    from backend.domain.execution import RuntimeEvent
    from backend.persistence import runs
    from backend.services.common import transaction
    from backend.services.plans import PlanService

    runner, travel, context = travel_setup

    async def exercise() -> None:
        draft = await initial_draft(travel, context)
        await PlanService(travel).confirm(context.user_id, draft.draft_id)
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, context.user_id, context.session_id, uuid4(), "旧事件", "offline"
            )
            old_context = RunContext(context.user_id, context.session_id, row.id)
            await runs.append_event(
                db, RuntimeEvent(old_context, "tool_finished", tool_name="stage_plan_change")
            )
            await runs.append_event(
                db,
                RuntimeEvent(
                    old_context,
                    "presentation",
                    presentation={"data": {"draft_id": str(draft.draft_id)}},
                ),
            )
            await runs.append_event(
                db, RuntimeEvent(old_context, "tool_finished", tool_name="stage_plan_change")
            )
            await runs.finish(db, old_context, RuntimeOutcome(text="已保存"))
        result = await RunService(travel.database).get(context.user_id, row.id)
        assert result.business_result is None and result.presentations
        page = await HistoryService(travel.database).runs(
            context.user_id, context.session_id, 20, None
        )
        assert page.items[0].business_result is None

    runner.run(exercise())


def test_foreign_session_draft_is_not_a_business_commit_for_this_turn(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    from backend.persistence import sessions
    from backend.services.common import transaction

    runner, travel, context = travel_setup

    async def exercise() -> None:
        draft = await initial_draft(travel, context)
        async with transaction(travel.database) as db:
            other = await sessions.create_session(db, context.user_id)
            sid = other.id
        service = RunService(
            travel.database,
            runtime_factory=lambda executor: StageRuntime((ToolResult(draft.summary()),)),
        )
        run = await service.submit(
            context.user_id, sid, MessageInput(client_message_id=uuid4(), text="异旅行引用")
        )
        await asyncio.gather(*tuple(service.tasks.values()))
        assert (await service.get(context.user_id, run.run_id)).business_result is None
        assert await version_count(travel, draft.plan_id) == 0
        await service.close()

    runner.run(exercise())


def test_answer_text_and_read_only_tools_cannot_claim_confirmation(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    service = RunService(travel.database, runtime_factory=lambda executor: StageRuntime(()))

    async def exercise() -> None:
        run = await service.submit(
            context.user_id,
            context.session_id,
            MessageInput(client_message_id=uuid4(), text="查询"),
        )
        await asyncio.gather(*tuple(service.tasks.values()))
        result = (await service.get(context.user_id, run.run_id)).business_result
        assert result is not None and result.kind == "answer_only" and result.version is None
        await service.close()

    runner.run(exercise())

"""工具错误不冒充成功；修正额度和最终失败缓存只属于当前业务操作。"""

import asyncio
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

from pydantic import BaseModel

from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.external_data import ExternalAttempt, ExternalDataError
from backend.services.travel import TravelService
from backend.tools.contracts import ToolResult
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor


class SyntheticExecutor(TravelToolExecutor):
    def __init__(self) -> None:
        super().__init__(
            cast(
                TravelService,
                type(
                    "T",
                    (),
                    {
                        "live": None,
                        "complete_conversation_task": AsyncMock(),
                    },
                )(),
            )
        )
        self.responses: list[ToolResult | ExternalDataError] = []
        self.sent = 0

    async def _dispatch(self, context: RunContext, name: str, parsed: BaseModel) -> ToolResult:
        self.sent += 1
        response = self.responses.pop(0)
        if isinstance(response, ExternalDataError):
            raise response
        return response


def test_hotel_results_report_actual_retry_and_closed_choice_state() -> None:
    async def exercise() -> None:
        for info in (
            ExternalAttempt(kind="bad_request", status=400, attempts=1),
            ExternalAttempt(kind="rate_limited", status=429, attempts=2),
        ):
            executor = SyntheticExecutor()
            executor.responses = [ExternalDataError("合成错误", info=info)]
            result = await executor.execute(
                RunContext(uuid4()), "search_hotel_offers", {"expected_revision": 1}
            )
            assert result.data["choice_card"] == "none"
            assert result.data["attempts"] == info.attempts
            assert result.data["auto_retried"] is (info.attempts > 1)
        executor = SyntheticExecutor()
        executor.responses = [ToolResult({"relaxation": {"declined": True}})]
        result = await executor.execute(
            RunContext(uuid4()), "search_hotel_offers", {"expected_revision": 1}
        )
        assert result.data["choice_card"] == "declined"

    asyncio.run(exercise())


def test_hotel_metadata_is_counted_inside_existing_result_limit() -> None:
    async def exercise() -> None:
        executor = SyntheticExecutor()
        executor.responses = [ToolResult({"padding": "x" * 7830})]
        result = await executor.execute(
            RunContext(uuid4()), "search_hotel_offers", {"expected_revision": 1}
        )
        assert result.code == "blocked" and "result_too_long" in result.detail

    asyncio.run(exercise())


def test_rejected_oversized_result_preserves_the_actual_http_attempts() -> None:
    async def exercise() -> None:
        executor = SyntheticExecutor()
        executor.responses = [
            ToolResult(
                {"padding": "x" * 7900},
                external=ExternalAttempt(attempts=2, recovered_from="timeout"),
            )
        ]
        result = await executor.execute(
            RunContext(uuid4()), "search_hotel_offers", {"expected_revision": 1}
        )
        assert result.code == "blocked"
        assert result.data["attempts"] == 2 and result.data["auto_retried"] is True

    asyncio.run(exercise())


def test_bad_request_allows_only_one_correction_and_is_provisional() -> None:
    async def exercise() -> None:
        executor = SyntheticExecutor()
        bad = ExternalDataError(
            "安全的参数错误", info=ExternalAttempt(kind="bad_request", status=400, attempts=1)
        )
        executor.responses = [bad, bad]
        context = RunContext(uuid4())
        events: list[RuntimeEvent] = []
        definition = next(d for d in DEFINITIONS if d.name == "search_places")
        first = await execute_observed(
            executor,
            context,
            "search_places",
            {"city": "京都", "query": "a"},
            events.append,
            definition=definition,
        )
        assert first.code == "validation"
        assert first.external and first.external.provisional
        assert not executor.stopping_error
        assert not any(e.kind == "presentation" for e in events)
        second = await executor.execute(context, "search_places", {"city": "京都", "query": "b"})
        assert second.code == "validation" and second.external and not second.external.provisional
        assert executor.stopping_error
        third = await executor.execute(context, "search_places", {"city": "京都", "query": "c"})
        assert third.code == "validation" and executor.sent == 2

    asyncio.run(exercise())


def test_unrelated_success_does_not_clear_pause_or_final_error_cache() -> None:
    async def exercise() -> None:
        executor = SyntheticExecutor()
        executor.responses = [
            ExternalDataError("超时", info=ExternalAttempt(kind="timeout", attempts=2)),
            ToolResult({}),
            ToolResult({}),
        ]
        context = RunContext(uuid4())
        args: dict[str, object] = {"city": "京都", "query": "a"}
        await executor.execute(context, "search_places", args)
        assert executor.stopping_error
        await executor.execute(context, "load_skill", {"name": "hotel-comparison"})
        assert executor.stopping_error
        await executor.execute(context, "search_places", args)
        assert executor.sent == 2
        await executor.execute(context, "search_places", {"city": "京都", "query": "b"})
        assert not executor.stopping_error

    asyncio.run(exercise())


def test_recovered_request_never_pauses_stop_hook() -> None:
    async def exercise() -> None:
        executor = SyntheticExecutor()
        executor.responses = [
            ToolResult({}, external=ExternalAttempt(attempts=2, recovered_from="timeout"))
        ]
        result = await executor.execute(RunContext(uuid4()), "search_places", {"city": "京都"})
        assert result.code is None and not executor.stopping_error

    asyncio.run(exercise())


def test_parameter_correction_then_transient_failure_cannot_obtain_third_query() -> None:
    async def exercise() -> None:
        executor = SyntheticExecutor()
        executor.responses = [
            ExternalDataError(
                "参数", info=ExternalAttempt(kind="bad_request", status=400, attempts=1)
            ),
            ExternalDataError(
                "服务", info=ExternalAttempt(kind="upstream_5xx", status=503, attempts=2)
            ),
            ToolResult({}),
        ]
        context = RunContext(uuid4())
        await executor.execute(context, "search_places", {"city": "京都", "query": "a"})
        second = await executor.execute(context, "search_places", {"city": "京都", "query": "b"})
        third = await executor.execute(context, "search_places", {"city": "京都", "query": "c"})
        assert second.code == third.code == "unavailable"
        assert executor.sent == 2

    asyncio.run(exercise())


def test_concurrent_identical_failures_only_dispatch_once() -> None:
    class YieldingExecutor(SyntheticExecutor):
        async def _dispatch(self, context: RunContext, name: str, parsed: BaseModel) -> ToolResult:
            await asyncio.sleep(0)
            return await super()._dispatch(context, name, parsed)

    async def exercise() -> None:
        executor = YieldingExecutor()
        failure = ExternalDataError(
            "服务", info=ExternalAttempt(kind="upstream_5xx", status=503, attempts=2)
        )
        executor.responses = [failure, failure]
        context = RunContext(uuid4())
        arguments: dict[str, object] = {"city": "京都"}
        results = await asyncio.gather(
            executor.execute(context, "search_places", arguments),
            executor.execute(context, "search_places", arguments),
        )
        assert all(result.code == "unavailable" for result in results)
        assert executor.sent == 1

    asyncio.run(exercise())


def test_repeated_bad_parameters_become_final_without_sending_again() -> None:
    async def exercise() -> None:
        executor = SyntheticExecutor()
        executor.responses = [
            ExternalDataError(
                "参数", info=ExternalAttempt(kind="bad_request", status=400, attempts=1)
            )
        ]
        context = RunContext(uuid4())
        arguments: dict[str, object] = {"city": "京都"}
        first = await executor.execute(context, "search_places", arguments)
        assert first.external and first.external.provisional
        repeated = await executor.execute(context, "search_places", arguments)
        assert repeated.external and not repeated.external.provisional
        assert executor.stopping_error and executor.sent == 1

    asyncio.run(exercise())


def test_service_attaches_each_signalled_skill_once_and_keeps_only_hash_in_event() -> None:
    async def exercise() -> None:
        executor = SyntheticExecutor()
        signals = ToolResult(
            {"relaxation": {"declined": True}},
            external=ExternalAttempt(kind="timeout", attempts=1),
            empty=True,
            detail=("repair_limit",),
            segmented=True,
        )
        executor.responses = [signals, signals]
        context = RunContext(uuid4())
        events: list[RuntimeEvent] = []
        name = "search_hotel_offers"
        definition = next(tool for tool in DEFINITIONS if tool.name == name)
        first = await execute_observed(
            executor, context, name, {"expected_revision": 1}, events.append, definition=definition
        )
        expected = {"multi-city", "budget-relaxation", "external-errors", "repair-limit"}
        assert {use.name for use, text in first.attached_skills if text} == expected
        finished = next(event for event in events if event.kind == "tool_finished")
        assert {use.name for use in finished.attached_skills} == expected
        assert all(len(use.sha256) == 64 for use in finished.attached_skills)
        assert first.payload()["skill_instructions"]
        presentation = next(event.presentation for event in events if event.presentation)
        assert "skill_instructions" not in presentation
        second = await executor.execute(context, name, {"expected_revision": 1})
        assert not second.attached_skills

    asyncio.run(exercise())

"""逐调用参数准确率须有语义证据；真实PG接受的合法日期也可能违背用户指定日期。"""

import asyncio

from backend.domain.execution import RunContext, RuntimeEvent
from backend.services.travel import TravelService
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from eval.cases import Case
from eval.diagnostics import ArgumentFact
from eval.metrics import tool_call_accuracy
from tests.integration.test_travel import travel_setup as travel_setup


def test_successful_database_patch_with_wrong_dates_does_not_get_accurate_call_credit(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R04/R17：验证真实参数/提交状态，不把成功返回当参数正确。"""
    runner, travel, context = travel_setup
    expected: dict[str, object] = {
        "expected_revision": 1,
        "set": {"start_date": "2026-11-03", "end_date": "2026-11-05"},
    }
    actual: dict[str, object] = {
        "expected_revision": 1,
        "set": {"start_date": "2026-11-10", "end_date": "2026-11-12"},
    }

    async def exercise() -> None:
        events: list[RuntimeEvent] = []
        result = await execute_observed(
            TravelToolExecutor(travel),
            context,
            "update_travel_request",
            actual,
            events.append,
            definition=next(d for d in DEFINITIONS if d.name == "update_travel_request"),
        )
        assert result.code is None
        request = await travel.get_request(context)
        assert request.start_date is not None
        assert request.start_date.isoformat() == "2026-11-10"
        call_id = events[0].tool_call_id
        assert call_id is not None
        case = Case(
            case_id="metric-date-control",
            source="self-authored",
            adaptation="known requested dates",
            input="11月3至5日京都旅行",
            allowed_tools=["update_travel_request"],
        )
        metric = tool_call_accuracy(
            case,
            tuple(events),
            (ArgumentFact(context, call_id, actual),),
            (ArgumentFact(context, call_id, expected),),
        )
        assert metric["incorrect"] == 1 and metric["accuracy"] == 0

    runner.run(exercise())

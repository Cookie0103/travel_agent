"""E5：写操作已提交后，结果超长不能报成失败（模型会重试出重复写入）；读工具仍按超长拒绝。"""

import asyncio

import pytest
from pydantic import BaseModel

from backend.domain.execution import RunContext
from backend.services.travel import TravelService
from backend.tools.contracts import RESULT_LIMIT, ToolResult
from backend.tools.travel import TravelToolExecutor
from tests.integration.test_planning import destinations, proposal
from tests.integration.test_travel import travel_setup as travel_setup
from tests.integration.user_turn import start_turn

pytestmark = pytest.mark.integration
Setup = tuple[asyncio.Runner, TravelService, RunContext]


@pytest.fixture
def bloated(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实执行后把结果撑过上限，模拟展示体积超限的写工具。"""
    original = TravelToolExecutor._dispatch

    async def dispatch(
        self: TravelToolExecutor, context: RunContext, name: str, parsed: BaseModel
    ) -> ToolResult:
        result = await original(self, context, name, parsed)
        return ToolResult(
            {**result.data, "padding": "长" * (RESULT_LIMIT + 10)},
            evidence_ids=result.evidence_ids,
            warnings=result.warnings,
        )

    monkeypatch.setattr(TravelToolExecutor, "_dispatch", dispatch)


def test_committed_state_write_with_oversized_result_reports_success(
    travel_setup: Setup, bloated: None
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        turn = await start_turn(travel, context, "房间数改成2间房")
        result = await TravelToolExecutor(travel).execute(
            turn,
            "update_travel_request",
            {"expected_revision": 1, "set": {"rooms": 2}, "explicit_fields": ["rooms"]},
        )
        assert result.code is None and "result_too_long" not in result.detail
        assert result.data["request_revision"] == 2 and "padding" not in result.data
        assert "已提交" in result.warnings[-1] and "不要重复" in result.warnings[-1]
        assert (await travel.read_request(context)).rooms == 2  # 写入确实发生

    runner.run(exercise())


def test_committed_draft_write_keeps_ids_and_read_tools_are_still_rejected(
    travel_setup: Setup, bloated: None
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        first, _ = await destinations(travel, context)
        executor = TravelToolExecutor(travel)
        staged = await executor.execute(
            context,
            "stage_plan_change",
            {"change": {"kind": "initial", "proposal": proposal(first).model_dump(mode="json")}},
        )
        assert staged.code is None
        assert {"draft_id", "plan_id"} <= set(staged.data) and "padding" not in staged.data
        searched = await executor.execute(context, "search_places", {"city": "京都", "limit": 1})
        assert searched.code == "blocked" and "result_too_long" in searched.detail

    runner.run(exercise())


def test_runtime_checks_are_not_asserts() -> None:
    """python -O 会删掉assert；工具层的运行时校验必须是显式判断。"""
    import ast
    import inspect
    import textwrap

    from backend.tools import travel

    source = inspect.getsource(travel.TravelToolExecutor._execute)
    assert not [
        n for n in ast.walk(ast.parse(textwrap.dedent(source))) if isinstance(n, ast.Assert)
    ]

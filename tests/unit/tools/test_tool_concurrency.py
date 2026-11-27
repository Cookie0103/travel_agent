"""纯查询可重叠执行；写工具仍逐个执行，调用与外部额度上限不被并发绕过。"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from pydantic import BaseModel

from backend.adapters.external_api import CALL_OBSERVATIONS, ApiUsage
from backend.domain.execution import RunContext
from backend.domain.external_data import ExternalAttempt, ExternalDataError
from backend.mcp.bridge import _build_tool
from backend.services.travel import TravelService
from backend.tools.contracts import ToolResult
from backend.tools.travel import DEFINITIONS, TravelToolExecutor


class OverlapExecutor(TravelToolExecutor):
    """记录同时处于_dispatch中的调用数；每次调用让出事件循环以暴露重叠。"""

    def __init__(self, *, live: object | None = None, max_calls: int | None = 16) -> None:
        super().__init__(cast(TravelService, SimpleNamespace(live=live)), max_calls=max_calls)
        self.active = self.peak = self.sent = 0

    async def _dispatch(self, context: RunContext, name: str, parsed: BaseModel) -> ToolResult:
        self.sent += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            for _ in range(5):
                await asyncio.sleep(0)
        finally:
            self.active -= 1
        return ToolResult({"name": name})


async def run_all(
    executor: TravelToolExecutor, *calls: tuple[str, dict[str, object]]
) -> list[ToolResult]:
    context = RunContext(uuid4())
    return await asyncio.wait_for(
        asyncio.gather(*(executor.execute(context, name, args) for name, args in calls)), 5
    )


def test_independent_reads_overlap() -> None:
    executor = OverlapExecutor()
    results = asyncio.run(
        run_all(
            executor,
            ("search_places", {"city": "京都", "query": "寺"}),
            ("get_place_facts", {"entity_id": "p1"}),
        )
    )
    assert all(result.code is None for result in results)
    assert executor.peak == 2


def test_write_and_unlisted_tools_stay_serial() -> None:
    executor = OverlapExecutor()
    asyncio.run(
        run_all(
            executor,
            ("search_hotel_offers", {"expected_revision": 1}),
            ("search_hotel_offers", {"expected_revision": 1, "limit": 3}),
            ("search_places", {"city": "京都", "query": "寺"}),
        )
    )
    # 酒店查询不在并发白名单，全程持锁；查询无法在其执行期间插入。
    assert executor.sent == 3 and executor.peak == 1


def test_concurrent_reads_cannot_exceed_call_cap() -> None:
    executor = OverlapExecutor(max_calls=2)
    calls: list[tuple[str, dict[str, object]]] = [
        ("search_places", {"city": "京都", "query": str(index)}) for index in range(4)
    ]
    results = asyncio.run(run_all(executor, *calls))
    assert executor.sent == 2
    assert sorted("tool_call_cap" in result.detail for result in results) == [
        False,
        False,
        True,
        True,
    ]


def test_each_concurrent_call_reports_its_own_external_attempt() -> None:
    class Observed(OverlapExecutor):
        async def _dispatch(self, context: RunContext, name: str, parsed: BaseModel) -> ToolResult:
            attempts = 2 if name == "search_places" else 1
            await asyncio.sleep(0)
            observed = CALL_OBSERVATIONS.get()
            assert observed is not None
            observed.append(ExternalAttempt(kind="upstream_5xx", status=503, attempts=attempts))
            await asyncio.sleep(0)
            return ToolResult({"name": name})

    executor = Observed(live=SimpleNamespace(data_mode="live"))
    places, facts = asyncio.run(
        run_all(
            executor,
            ("search_places", {"city": "京都", "query": "寺"}),
            ("get_place_facts", {"entity_id": "p1"}),
        )
    )
    assert places.external is not None and places.external.attempts == 2
    assert facts.external is not None and facts.external.attempts == 1


def test_only_concurrent_reads_are_advertised_read_only() -> None:
    def hint(name: str) -> object:
        definition = next(d for d in DEFINITIONS if d.name == name)
        tool = _build_tool(definition, OverlapExecutor(), RunContext(uuid4()), lambda e: None)
        if tool.annotations is None:
            return None
        # CLI读取线上别名readOnlyHint(SDK按by_alias序列化tools/list)。
        return tool.annotations.model_dump(by_alias=True, exclude_none=True).get("readOnlyHint")

    assert hint("search_places") is True and hint("get_weather_forecast") is True
    assert hint("search_hotel_offers") is None and hint("stage_plan_change") is None


@pytest.mark.asyncio
async def test_concurrent_consumers_cannot_pass_run_cap_together() -> None:
    class Session:
        async def scalar(self, *args: object) -> int:
            await asyncio.sleep(0)
            return 1

    @asynccontextmanager
    async def begin():  # type: ignore[no-untyped-def]
        yield Session()

    usage = ApiUsage.__new__(ApiUsage)
    usage.database = cast(object, SimpleNamespace(sessions=SimpleNamespace(begin=begin)))  # type: ignore[assignment]
    usage.run_caps, usage.daily, usage.used, usage.run_limits = (
        {"places": 1},
        {"places": 10},
        {},
        True,
    )
    outcomes = await asyncio.gather(
        usage.consume("places"), usage.consume("places"), return_exceptions=True
    )
    assert sum(isinstance(item, ExternalDataError) for item in outcomes) == 1
    assert usage.used == {"places": 1}

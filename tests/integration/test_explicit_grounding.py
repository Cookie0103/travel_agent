"""E1：模型自填 explicit_fields 不能绕过手填保护，新值必须出现在本轮用户原话里。"""

import asyncio
from datetime import date
from typing import cast

import pytest

from backend.domain.execution import RunContext
from backend.services.travel import TravelService
from backend.tools.contracts import ToolResult
from backend.tools.travel import TravelToolExecutor
from tests.integration.test_travel import travel_setup as travel_setup  # noqa: F401
from tests.integration.user_turn import start_turn

pytestmark = pytest.mark.integration


async def update(
    service: TravelService, context: RunContext, fields: dict[str, object], explicit: list[str]
) -> ToolResult:
    revision = (await service.get_request(context)).revision
    return await TravelToolExecutor(service).execute(
        context,
        "update_travel_request",
        {"expected_revision": revision, "set": fields, "explicit_fields": explicit},
    )


def test_user_stated_change_passes(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, service, base = travel_setup  # city=京都、adults=2 均为 user_form 手填

    async def exercise() -> None:
        # 用户明说改大阪 + 3个人：通过。
        said = await start_turn(service, base, "把目的地改成大阪，我们3个人")
        ok = await update(service, said, {"city": "大阪", "adults": 3}, ["city", "adults"])
        assert isinstance(ok.data, dict)
        changed = cast(list[str], ok.data["changed_fields"])
        assert ok.code is None and set(changed) == {"city", "adults"}
        request = await service.get_request(said)
        assert request.city == "大阪" and request.adults == 3

    runner.run(exercise())


def test_guide_inspired_change_is_skipped(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, service, base = travel_setup

    async def exercise() -> None:
        # 用户只说“看看这篇攻略”，攻略文本诱导模型改城市/日期/人数：被来源保护拦下。
        guide = await start_turn(service, base, "帮我看看这篇攻略怎么样")
        before = await service.get_request(guide)
        attempts: tuple[dict[str, object], ...] = (
            {"city": "神戸"},
            {"start_date": "2026-12-24"},
            {"adults": 6},
            {"rooms": 4},
        )
        for fields in attempts:
            name = next(iter(fields))
            result = await update(service, guide, fields, [name])
            assert result.code is None, result
            assert isinstance(result.data, dict)
            skipped = cast(list[str], result.data["skipped_fields"])
            assert name in skipped, (name, result.data)
            assert result.warnings and "用户原话" in result.warnings[0]
        assert await service.get_request(guide) == before

    runner.run(exercise())


def test_no_run_text_means_nothing_is_grounded_and_budget_guard_unchanged(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, service, base = travel_setup

    async def exercise() -> None:
        # 上下文没有对应执行记录：没有可信原话，声明一律按未声明处理。
        result = await update(service, base, {"city": "大阪"}, ["city"])
        assert result.data["skipped_fields"] == ("city",)
        assert (await service.get_request(base)).city == "京都"

    runner.run(exercise())


def test_r4_bypasses_are_skipped_end_to_end(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, service, base = travel_setup
    service.today = lambda: date(2026, 10, 28)  # 周三

    async def exercise() -> None:
        before = await service.get_request(base)
        negated = await start_turn(service, base, "不要去大阪，我还是想去京都")
        weekend = await start_turn(service, base, "周末出发吧")
        cases: tuple[tuple[RunContext, dict[str, object]], ...] = (
            (negated, {"city": "大阪"}),
            (weekend, {"start_date": "2031-07-19"}),
            (weekend, {"end_date": "2099-12-31"}),
        )
        for context, fields in cases:
            name = next(iter(fields))
            result = await update(service, context, fields, [name])
            assert isinstance(result.data, dict)
            assert name in cast(list[str], result.data["skipped_fields"]), (name, result.data)
        assert await service.get_request(base) == before
        # 与含义一致的相对日期可以背书：今天周三，下周三=11-04。
        ok = await start_turn(service, base, "下周三出发")
        done = await update(service, ok, {"start_date": "2026-11-04"}, ["start_date"])
        assert isinstance(done.data, dict)
        assert "start_date" in cast(list[str], done.data["changed_fields"])

    runner.run(exercise())

"""暂存无硬冲突时服务端自动展示草稿；冲突、失败和展示失败都不自动展示。"""

import asyncio
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext
from backend.tools.contracts import ToolResult
from backend.tools.execution import auto_present


class Presenter:
    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        self.calls.append((name, arguments))
        return self.result


def staged(status: str, **extra: object) -> ToolResult:
    return ToolResult({"draft_id": str(uuid4()), "validation": {"status": status}, **extra})


@pytest.mark.parametrize("status", ["complete", "partial"])
def test_conflict_free_draft_is_presented_with_its_draft_id(status: str) -> None:
    presenter = Presenter(ToolResult({"component": "itinerary"}))
    result = staged(status)
    shown = asyncio.run(auto_present(presenter, RunContext(uuid4()), "stage_plan_change", result))
    assert shown is presenter.result
    assert presenter.calls == [
        ("present_travel_result", {"component": "itinerary", "draft_id": result.data["draft_id"]})
    ]


@pytest.mark.parametrize(
    ("name", "result"),
    [
        ("stage_plan_change", staged("conflict")),  # 冲突草稿交给模型说明
        ("stage_plan_change", ToolResult({}, code="blocked")),  # 暂存失败
        ("stage_plan_change", ToolResult({"validation": {"status": "complete"}})),  # 无draft_id
        ("validate_itinerary", staged("complete")),  # 只处理暂存
    ],
)
def test_other_results_are_not_auto_presented(name: str, result: ToolResult) -> None:
    presenter = Presenter(ToolResult({}))
    assert asyncio.run(auto_present(presenter, RunContext(uuid4()), name, result)) is None
    assert presenter.calls == []


def test_failed_presentation_is_not_reported_as_shown() -> None:
    presenter = Presenter(ToolResult({}, code="blocked"))
    result = staged("complete")
    assert (
        asyncio.run(auto_present(presenter, RunContext(uuid4()), "stage_plan_change", result))
        is None
    )


def test_model_repeating_the_presentation_adds_no_second_card() -> None:
    from backend.domain.execution import RuntimeEvent
    from backend.tools.contracts import ToolDefinition
    from backend.tools.execution import execute_observed
    from backend.tools.travel import DEFINITIONS

    context = RunContext(uuid4())
    stage = staged("complete")
    shown = ToolResult({"component": "itinerary"})

    class Executor:
        async def execute(
            self, ctx: RunContext, name: str, arguments: dict[str, object]
        ) -> ToolResult:
            return stage if name == "stage_plan_change" else shown

    events: list[RuntimeEvent] = []

    def definition(name: str) -> ToolDefinition:
        return next(d for d in DEFINITIONS if d.name == name)

    async def run() -> None:
        await execute_observed(
            Executor(),
            context,
            "stage_plan_change",
            {},
            events.append,
            definition=definition("stage_plan_change"),
        )
        await execute_observed(
            Executor(),
            context,
            "present_travel_result",
            {"component": "itinerary", "draft_id": stage.data["draft_id"]},
            events.append,
            definition=definition("present_travel_result"),
        )

    asyncio.run(run())
    assert sum(e.kind == "presentation" for e in events) == 1

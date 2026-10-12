"""评测固定流程的顺序约束；仅守门工具调用，模型与工具循环仍由SDK运行。"""

import asyncio
from typing import Literal

from backend.domain.execution import RunContext
from backend.tools.contracts import ToolExecutor, ToolResult

WorkflowName = Literal["search", "hotel", "itinerary"]
WORKFLOWS: dict[WorkflowName, tuple[frozenset[str], ...]] = {
    "search": (frozenset({"search_places"}), frozenset({"search_content"})),
    "hotel": (
        frozenset({"search_hotel_offers", "refresh_hotel_offer"}),
        frozenset({"present_travel_result"}),
    ),
    "itinerary": (
        frozenset({"search_places", "search_content", "get_article", "get_place_facts"}),
        frozenset({"search_hotel_offers", "refresh_hotel_offer"}),
        frozenset({"estimate_routes"}),
        frozenset({"validate_itinerary"}),
        frozenset({"stage_plan_change"}),
        frozenset({"present_travel_result"}),
    ),
}


def workflow_guidance(name: WorkflowName) -> str:
    steps = " → ".join("/".join(sorted(step)) for step in WORKFLOWS[name])
    return (
        f"\n评测固定流程：{steps}。可在当前阶段重复查询/修复，不跳过阶段。"
        "开始前可更新旅行条件，load_skill可随时使用。缺少条件先追问，不能猜测。"
        "参数、来源和方案仍须根据当前事实生成；确认与业务规则不变。"
    )


class OrderedTools:
    def __init__(self, executor: ToolExecutor, name: WorkflowName) -> None:
        self.executor, self.steps = executor, WORKFLOWS[name]
        self.position = -1
        self.context: RunContext | None = None
        self.lock = asyncio.Lock()

    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        async with self.lock:
            if self.context is not None and self.context != context:
                return ToolResult({}, code="blocked", suggestion="固定流程仅属于当前执行")
            self.context = context
            setup = name == "load_skill" or (name == "update_travel_request" and self.position < 0)
            index = next((i for i, step in enumerate(self.steps) if name in step), None)
            if not setup and (index is None or index not in {self.position, self.position + 1}):
                return ToolResult(
                    {}, code="blocked", suggestion="请完成固定流程当前阶段，不跳过或回退"
                )
            result = await self.executor.execute(context, name, arguments)
            # 不变量：失败或空结果不能推进流程；底层仍执行原有版本/证据/事务检查。
            if not setup and index is not None and result.code is None and not result.empty:
                self.position = index
            return result

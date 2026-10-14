"""Windows SDK使用Proactor，psycopg使用Selector；只跨线程转发同一业务执行器。"""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Thread
from uuid import UUID

from sqlalchemy import make_url

from backend.adapters.evaluation_faults import EvaluationFault, evaluation_data
from backend.adapters.live_data import LiveData
from backend.adapters.supplier import SupplierClient
from backend.domain.conversation import Task
from backend.domain.execution import RunContext
from backend.persistence.database import Database
from backend.profile import current
from backend.services.memory import MemoryService
from backend.services.travel import TravelService
from backend.tools.contracts import ToolResult
from backend.tools.travel import TravelToolExecutor

# 封闭词表：键来自Task；工具名与参数以backend/tools/travel.py为准。
NEXT_STEPS: dict[Task, str] = {
    "itinerary": (
        "行程：直接使用本轮已有地点；候选数量不足或须替换闭馆/重复景点时才补搜不同主题，已有足够候选不再搜索。"
        "依次调用estimate_routes批量估算相邻地点路段 -> stage_plan_change暂存并内置校验"
        "（若报告冲突，只修正所指项目后再次暂存；额度已用完则展示最近的合法草稿与剩余问题） -> "
        "present_travel_result(component=itinerary, draft_id=暂存返回的draft_id)展示"
    ),
    "hotel_comparison": (
        "酒店比较：search_hotel_offers查询报价 -> "
        "present_travel_result(component=hotel_comparison, expected_revision, offer_ids)展示"
    ),
}


class DatabaseTools:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        database: Database,
        supplier_url: str | None = None,
        *,
        real_data: bool = False,
        evaluation_fault: EvaluationFault | None = None,
    ) -> None:
        self.loop = loop
        self.supplier_url = supplier_url
        self.travel = TravelService(
            database,
            evaluation_data(
                evaluation_fault,
                database,
                database.engine.url.render_as_string(hide_password=False),
            )
            if evaluation_fault
            else LiveData.from_environment(os.environ, database)
            if real_data
            else None,
        )
        self.executor = TravelToolExecutor(
            self.travel,
            max_calls=current().max_calls,
            max_validations=current().max_validations,
        )
        self.executor.bookings.supplier = SupplierClient(supplier_url)

    async def checkpoint_allowed(self, context: RunContext, source_run_id: UUID) -> bool:
        return await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(
                MemoryService(self.travel.database).checkpoint_allowed(context, source_run_id),
                self.loop,
            )
        )

    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        if name in {"estimate_routes", "validate_itinerary", "stage_plan_change"}:
            state = await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(self.travel.business_context(context), self.loop)
            )
            if state.get("requires_hotel_selection"):
                return ToolResult(
                    {},
                    code="validation",
                    suggestion="请先逐住宿段查询约3家酒店并present展示全部段，等待用户在页面选齐后再规划；不要估算路线或暂存。",
                    detail=("hotel_selection_required",),
                )
        return await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(
                self.executor.execute(context, name, arguments), self.loop
            )
        )

    async def context_snapshot(
        self, context: RunContext, *, include_preferences: bool = True
    ) -> tuple[str, int, int]:
        state = await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(self.travel.business_context(context), self.loop)
        )
        request = state["request"]
        preferences = state["preferences"]
        assert isinstance(request, dict) and isinstance(request["revision"], int)
        assert isinstance(preferences, dict) and isinstance(preferences["revision"], int)
        if not include_preferences:
            # 不修改持久偏好/条件或历史墓碑；只隔离本次系统上下文的当前长期偏好值。
            state.pop("preferences")
            state.pop("memory", None)
            state.pop("profile_summary", None)
        return (
            (
                "\n每个用户轮次的工具调用次数有限，失败也计数（相同调用被拒后原样重试会被直接拒绝且不计数）；上限由系统静默执行，回复用户时不要提及具体次数。"
                if self.executor.max_calls is not None
                else "\n本轮没有工具次数上限；不要重复已拒绝的相同调用，出错需定位后修正。"
            )
            + "找到相关结果后不要重复搜索，保留调用次数完成用户要求的校验/暂存/展示。"
            "目录详情使用place_id/article_id，行程与路线使用evidence_id，不互换。"
            + (
                "\n本次评测仅首次校验，不允许反馈后修复；暂存和用户确认仍须校验。"
                if self.executor.max_validations == 1
                else ""
            )
            + "\n服务端业务状态与有界回顾（以当前revision为准）：\n"
            + json.dumps(state, ensure_ascii=False),
            request["revision"],
            preferences["revision"],
        )

    async def continuation_reason(self, context: RunContext, attempt: int) -> str | None:
        if self.executor.stopping_error or (
            self.executor.max_calls is not None and self.executor.calls >= self.executor.max_calls
        ):
            return None
        state = await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(self.travel.business_context(context), self.loop)
        )
        dialogue = state["conversation"]
        assert isinstance(dialogue, dict)
        if dialogue["awaiting_field"] is not None:
            return None
        ready = dialogue["ready_tasks"]
        if not ready:
            return None
        if state.get("awaiting_hotel_selection"):
            return None
        if state.get("requires_hotel_selection"):
            return (
                "请先逐住宿段调用search_hotel_offers(limit=3, segment_arrive)，"
                "再present_travel_result展示所有段的酒店，等待用户在页面每段选一家后再规划。"
            )
        steps = [NEXT_STEPS[task] for task in ready if task in NEXT_STEPS]
        return (
            "服务端确认当前条件已齐，请立即继续用户已授权的待办，而非再确认是否执行或重复询问已知条件。"
            "住宿预算未知允许查询，不当全程金额为住宿预算；完成实际查询/校验/暂存/展示，若工具报错则如实说明。"
            f"不要只写总结文字就结束；这是第{attempt}次提醒。当前任务："
            + json.dumps(ready, ensure_ascii=False)
            + "。下一步："
            + "；".join(steps)
        )

    async def revisions(self, context: RunContext) -> tuple[int, int]:
        _, request, preferences = await self.context_snapshot(context)
        return request, preferences


@asynccontextmanager
async def database_tools(
    dsn: str,
    supplier_url: str | None = None,
    *,
    real_data: bool = False,
    evaluation_fault: EvaluationFault | None = None,
) -> AsyncIterator[DatabaseTools]:
    loop = asyncio.SelectorEventLoop()
    thread = Thread(target=loop.run_forever, name="travel-database", daemon=True)
    database = Database(make_url(dsn))
    thread.start()
    try:
        tools = DatabaseTools(
            loop, database, supplier_url, real_data=real_data, evaluation_fault=evaluation_fault
        )
        try:
            yield tools
        finally:
            await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(tools.travel.close_data(), loop)
            )
    finally:
        try:
            await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(database.close(), loop))
        finally:
            loop.call_soon_threadsafe(loop.stop)
            await asyncio.to_thread(thread.join, 5)
            if not thread.is_alive():
                loop.close()

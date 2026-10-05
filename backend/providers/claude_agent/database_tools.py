"""Windows SDK使用Proactor，psycopg使用Selector；只跨线程转发同一业务执行器。"""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Thread

from sqlalchemy import make_url

from backend.adapters.live_data import LiveData
from backend.adapters.supplier import SupplierClient
from backend.domain.execution import RunContext
from backend.persistence.database import Database
from backend.providers.claude_agent.profile import current
from backend.services.travel import TravelService
from backend.tools.contracts import ToolResult
from backend.tools.travel import TravelToolExecutor


class DatabaseTools:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        database: Database,
        supplier_url: str | None = None,
        *,
        real_data: bool = False,
    ) -> None:
        self.loop = loop
        self.supplier_url = supplier_url
        self.travel = TravelService(
            database, LiveData.from_environment(os.environ, database) if real_data else None
        )
        self.executor = TravelToolExecutor(
            self.travel,
            max_calls=current().max_calls,
            max_validations=current().max_validations,
        )
        self.executor.bookings.supplier = SupplierClient(supplier_url)

    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
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
        return (
            "\n每个用户轮次的工具调用次数有限，失败也计数；上限由系统静默执行，回复用户时不要提及具体次数。"
            "找到相关结果后不要重复搜索，保留调用次数完成用户要求的校验/暂存/展示。"
            "目录详情使用place_id/article_id，行程与路线使用evidence_id，不互换。"
            + (
                "\n本次评测仅首次校验，不允许反馈后修复；暂存和用户确认仍须校验。"
                if self.executor.max_validations == 1
                else ""
            )
            + (
                f"\n本次首次校验后最多修复{self.executor.max_validations - 1}轮，"
                "以此为准（覆盖前文的3轮说法）。"
                if self.executor.max_validations > 4
                else ""
            )
            + "\n服务端业务状态与有界回顾（以当前revision为准）：\n"
            + json.dumps(state, ensure_ascii=False),
            request["revision"],
            preferences["revision"],
        )

    async def revisions(self, context: RunContext) -> tuple[int, int]:
        _, request, preferences = await self.context_snapshot(context)
        return request, preferences


@asynccontextmanager
async def database_tools(
    dsn: str, supplier_url: str | None = None, *, real_data: bool = False
) -> AsyncIterator[DatabaseTools]:
    loop = asyncio.SelectorEventLoop()
    thread = Thread(target=loop.run_forever, name="travel-database", daemon=True)
    database = Database(make_url(dsn))
    thread.start()
    try:
        tools = DatabaseTools(loop, database, supplier_url, real_data=real_data)
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

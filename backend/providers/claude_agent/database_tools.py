"""Windows SDK使用Proactor，psycopg使用Selector；只跨线程转发同一业务执行器。"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Thread

from sqlalchemy import make_url

from backend.adapters.supplier import SupplierClient
from backend.domain.execution import RunContext
from backend.persistence.database import Database
from backend.services.travel import TravelService
from backend.tools.contracts import ToolResult
from backend.tools.travel import TravelToolExecutor


class DatabaseTools:
    def __init__(
        self, loop: asyncio.AbstractEventLoop, database: Database, supplier_url: str | None = None
    ) -> None:
        self.loop = loop
        self.travel = TravelService(database)
        self.executor = TravelToolExecutor(self.travel)
        self.executor.bookings.supplier = SupplierClient(supplier_url)

    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        return await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(
                self.executor.execute(context, name, arguments), self.loop
            )
        )

    async def context_snapshot(self, context: RunContext) -> tuple[str, int]:
        state = await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(self.travel.business_context(context), self.loop)
        )
        request = state["request"]
        assert isinstance(request, dict) and isinstance(request["revision"], int)
        return (
            "\n服务端业务状态与有界回顾（以当前revision为准）：\n"
            + json.dumps(state, ensure_ascii=False),
            request["revision"],
        )

    async def revision(self, context: RunContext) -> int:
        request = await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(self.travel.get_request(context), self.loop)
        )
        return request.revision


@asynccontextmanager
async def database_tools(dsn: str, supplier_url: str | None = None) -> AsyncIterator[DatabaseTools]:
    loop = asyncio.SelectorEventLoop()
    thread = Thread(target=loop.run_forever, name="travel-database", daemon=True)
    database = Database(make_url(dsn))
    thread.start()
    try:
        yield DatabaseTools(loop, database, supplier_url)
    finally:
        try:
            await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(database.close(), loop))
        finally:
            loop.call_soon_threadsafe(loop.stop)
            await asyncio.to_thread(thread.join, 5)
            if not thread.is_alive():
                loop.close()

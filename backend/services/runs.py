"""单进程消息执行用例：去重/取消/事件落库；模型编排仍只调用现有Agent与SDK。"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.agent.fixture_runtime import FixtureRuntime
from backend.agent.runtime import Agent, Runtime
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeOutcome
from backend.persistence import runs, sessions
from backend.persistence.database import Database
from backend.persistence.models import TaskRunRow
from backend.providers.claude_agent.application import GuardedRuntime
from backend.services.common import ServiceError, transaction
from backend.services.travel import TravelService
from backend.tools.contracts import ToolExecutor
from backend.tools.travel import TravelToolExecutor

LOGGER = logging.getLogger(__name__)
RUN_TIMEOUT = 150.0


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    client_message_id: UUID
    text: str = Field(min_length=1, max_length=4000)
    mode: Literal["offline", "live"] = "offline"


@dataclass(frozen=True)
class RunView:
    run_id: UUID
    session_id: UUID
    status: str
    mode: str
    answer: str
    error_code: str | None
    last_sequence: int
    created_at: datetime
    presentations: tuple[dict[str, object], ...] = ()


def view(row: TaskRunRow | None) -> RunView:
    if row is None:
        raise ServiceError(404, "blocked", "执行不存在")
    return RunView(
        row.id,
        row.session_id,
        row.status,
        row.mode,
        row.answer,
        row.error_code,
        row.last_sequence,
        row.created_at,
    )


class RunService:
    def __init__(
        self,
        database: Database,
        *,
        live_enabled: bool = False,
        runtime_factory: Callable[[ToolExecutor], Runtime] | None = None,
    ) -> None:
        self.database, self.live_enabled = database, live_enabled
        self.runtime_factory = runtime_factory
        self.tasks: dict[UUID, asyncio.Task[None]] = {}
        self.cancelled: dict[UUID, asyncio.Event] = {}
        self.persistence_failures: set[UUID] = set()

    async def submit(self, user_id: UUID, session_id: UUID, message: MessageInput) -> RunView:
        if message.mode == "live" and not self.live_enabled:
            raise ServiceError(403, "blocked", "API真实模型模式未启用")
        async with transaction(self.database) as db:
            if await sessions.get_session(db, user_id, session_id, lock=True) is None:
                raise ServiceError(404, "blocked", "会话不存在")
            previous = await runs.by_message(db, session_id, message.client_message_id)
            if previous is not None:
                if (previous.prompt, previous.mode) != (message.text, message.mode):
                    raise ServiceError(409, "conflict", "同一消息ID不能对应不同内容或模式")
                return view(previous)
            if await runs.active(db, session_id):
                raise ServiceError(409, "conflict", "此会话已有执行，请先等待或取消")
            row = await runs.create(
                db, user_id, session_id, message.client_message_id, message.text, message.mode
            )
            result = view(row)
        context = RunContext(user_id, session_id, result.run_id)
        self.cancelled[result.run_id] = asyncio.Event()
        self.tasks[result.run_id] = asyncio.create_task(self._execute(context, message))
        return result

    async def get(self, user_id: UUID, run_id: UUID) -> RunView:
        async with transaction(self.database) as db:
            result = view(await runs.owned(db, user_id, run_id))
            result = replace(result, presentations=await runs.presentations(db, run_id))
        if run_id in self.persistence_failures:
            raise ServiceError(503, "unavailable", "执行记录写入失败，需要恢复核对")
        return result

    async def events(self, user_id: UUID, run_id: UUID, after: int) -> list[dict[str, object]]:
        if after < 0:
            raise ServiceError(422, "validation", "事件游标不能为负")
        async with transaction(self.database) as db:
            view(await runs.owned(db, user_id, run_id))
            return [
                {"sequence": row.sequence, **row.payload}
                for row in await runs.events(db, run_id, after)
            ]

    async def cancel(self, user_id: UUID, run_id: UUID) -> RunView:
        async with transaction(self.database) as db:
            row = await runs.owned(db, user_id, run_id, lock=True)
            result = view(row)
            if result.status not in runs.ACTIVE:
                return result
            if run_id not in self.cancelled:
                raise ServiceError(409, "conflict", "原执行进程已退出，需要恢复核对")
            assert row is not None
            row.status = "cancelling"
            self.cancelled[run_id].set()
            return view(row)

    def _runtime(self, mode: str, executor: ToolExecutor) -> Runtime:
        if self.runtime_factory is not None:
            return self.runtime_factory(executor)
        if mode == "offline":
            return FixtureRuntime(executor)
        return GuardedRuntime(
            Path(__file__).resolve().parents[2],
            self.database.engine.url.render_as_string(hide_password=False),
        )

    async def _persist_events(
        self, context: RunContext, queue: asyncio.Queue[RuntimeEvent | None]
    ) -> None:
        while (event := await queue.get()) is not None:
            try:
                async with transaction(self.database) as db:
                    await runs.append_event(db, event)
            except Exception:
                self.cancelled[context.run_id].set()
                raise

    async def _execute(self, context: RunContext, message: MessageInput) -> None:
        queue: asyncio.Queue[RuntimeEvent | None] = asyncio.Queue()
        consumer = asyncio.create_task(self._persist_events(context, queue))
        outcome = RuntimeOutcome(code="provider_error", reason="execution_failed")

        def emit(event: RuntimeEvent) -> None:
            # 终态由finish和状态原子落库，避免SSE先看到完成、数据库却仍在运行。
            if event.kind not in {"completed", "failed", "cancelled"}:
                queue.put_nowait(event)

        try:
            executor = TravelToolExecutor(TravelService(self.database))
            agent = Agent(self._runtime(message.mode, executor))
            deadline = asyncio.timeout(RUN_TIMEOUT)
            async with deadline:
                result = await agent.run(
                    context,
                    message.text,
                    emit,
                    cancelled=self.cancelled[context.run_id],
                )
            outcome = (
                RuntimeOutcome(text=result.outcome.text, code="timeout", reason="run_timeout")
                if deadline.expired()
                else result.outcome
            )
        except asyncio.CancelledError:
            outcome = RuntimeOutcome(code="cancelled", reason="cancelled")
        except TimeoutError:
            outcome = RuntimeOutcome(code="timeout", reason="run_timeout")
        except Exception:
            outcome = RuntimeOutcome(code="provider_error", reason="execution_failed")
        finally:
            queue.put_nowait(None)
            try:
                await consumer
                async with transaction(self.database) as db:
                    await runs.finish(db, context, outcome)
            except Exception:
                self.persistence_failures.add(context.run_id)
                LOGGER.error("TaskRun persistence failed: %s", context.run_id)
            self.cancelled.pop(context.run_id, None)
            self.tasks.pop(context.run_id, None)

    async def close(self) -> None:
        for event in self.cancelled.values():
            event.set()
        await asyncio.gather(*tuple(self.tasks.values()), return_exceptions=True)

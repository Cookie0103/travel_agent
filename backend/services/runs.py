"""单进程消息执行用例：去重/取消/事件落库；模型编排仍只调用现有Agent与SDK。"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from backend.adapters.tracing import TraceMetadata, write_trace
from backend.agent.fixture_runtime import FixtureRuntime
from backend.agent.runtime import Agent, Runtime
from backend.domain.execution import (
    RunContext,
    RuntimeEvent,
    RuntimeIdentity,
    RuntimeOutcome,
    event_metadata,
)
from backend.persistence import runs, sessions
from backend.persistence.database import Database
from backend.persistence.models import TaskRunRow
from backend.providers.claude_agent.application import GuardedRuntime
from backend.services.common import ServiceError, database_error_details, transaction
from backend.services.travel import TravelService
from backend.tools.contracts import ToolExecutor
from backend.tools.travel import TravelToolExecutor

LOGGER = logging.getLogger(__name__)
RUN_TIMEOUT = 150.0


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    client_message_id: UUID
    text: str = Field(min_length=1, max_length=4000)
    mode: Literal["offline", "deepseek", "claude"] = "offline"


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
        trace_directory: Path | None = None,
        trace_cloud: bool = False,
    ) -> None:
        self.database, self.live_enabled = database, live_enabled
        self.runtime_factory = runtime_factory
        self.trace_cloud = trace_cloud
        self.trace_directory = (
            trace_directory or Path(__file__).resolve().parents[2] / ".cache" / "api-traces"
        )
        self.tasks: dict[UUID, asyncio.Task[None]] = {}
        self.cancelled: dict[UUID, asyncio.Event] = {}
        self.persistence_failures: set[UUID] = set()
        self.recovery_pending = False
        self.recovery_lock = asyncio.Lock()
        self.live_answers: dict[UUID, tuple[datetime, str]] = {}

    async def initialize(self, *, only_pending: bool = False) -> None:
        """单API进程启动：释放中断执行，不自动重复任何付费或预订操作。"""
        async with self.recovery_lock:
            if only_pending and not self.recovery_pending:
                return
            if self.tasks:
                raise RuntimeError("只能在接受消息前恢复旧执行")
            self.recovery_pending = True
            try:
                async with transaction(self.database) as db:
                    for row in await runs.interrupted(db):
                        context = RunContext(row.user_id, row.session_id, row.id)
                        await sessions.get_session(db, row.user_id, row.session_id, lock=True)
                        await runs.recover(db, context)
            except ServiceError as error:
                if error.code != "unavailable":
                    raise
                LOGGER.warning("TaskRun recovery waiting for database")
                return
            self.recovery_pending = False

    async def _require_recovery(self) -> None:
        if self.recovery_pending:
            await self.initialize(only_pending=True)
            if self.recovery_pending:
                raise ServiceError(503, "unavailable", "数据库恢复核对尚未完成")

    async def submit(self, user_id: UUID, session_id: UUID, message: MessageInput) -> RunView:
        await self._require_recovery()
        if message.mode != "offline" and not self.live_enabled:
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
        await self._require_recovery()
        async with transaction(self.database) as db:
            result = view(await runs.owned(db, user_id, run_id))
            result = replace(result, presentations=await runs.presentations(db, run_id))
        if run_id in self.persistence_failures:
            raise ServiceError(503, "unavailable", "执行记录写入失败，需要恢复核对")
        now = datetime.now(result.created_at.tzinfo)
        self.live_answers = {
            key: value
            for key, value in self.live_answers.items()
            if (now - value[0]).total_seconds() < 900
        }
        if run_id in self.live_answers:
            result = replace(result, answer=self.live_answers[run_id][1])
        return result

    async def events(self, user_id: UUID, run_id: UUID, after: int) -> list[dict[str, object]]:
        await self._require_recovery()
        if after < 0:
            raise ServiceError(422, "validation", "事件游标不能为负")
        async with transaction(self.database) as db:
            view(await runs.owned(db, user_id, run_id))
            return [
                {"sequence": row.sequence, **row.payload}
                for row in await runs.events(db, run_id, after)
            ]

    async def cancel(self, user_id: UUID, run_id: UUID) -> RunView:
        await self._require_recovery()
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
            provider="anthropic" if mode == "claude" else "deepseek",
            real_data=True,
        )

    async def _persist_events(
        self,
        context: RunContext,
        queue: asyncio.Queue[RuntimeEvent | None],
        *,
        transient: bool = False,
    ) -> None:
        while (event := await queue.get()) is not None:
            try:
                async with transaction(self.database) as db:
                    await runs.append_event(db, event_metadata(event) if transient else event)
            except Exception:
                self.cancelled[context.run_id].set()
                raise

    async def _execute(self, context: RunContext, message: MessageInput) -> None:
        queue: asyncio.Queue[RuntimeEvent | None] = asyncio.Queue()
        transient = message.mode != "offline" and self.runtime_factory is None
        consumer = asyncio.create_task(self._persist_events(context, queue, transient=transient))
        outcome = RuntimeOutcome(code="provider_error", reason="execution_failed")
        identity: RuntimeIdentity | None = None
        runtime: Runtime | None = None

        def emit(event: RuntimeEvent) -> None:
            # 终态由finish和状态原子落库，避免SSE先看到完成、数据库却仍在运行。
            if event.kind not in {"completed", "failed", "cancelled"}:
                queue.put_nowait(event)

        try:
            executor = TravelToolExecutor(TravelService(self.database))
            runtime = self._runtime(message.mode, executor)
            identity = runtime.identity
            agent = Agent(runtime)
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
                if transient:
                    self.live_answers[context.run_id] = (datetime.now().astimezone(), outcome.text)
                    outcome = replace(
                        outcome,
                        text="实时回复仅供本轮查看；行程引用已保存，详情按需更新。"
                        if outcome.code is None
                        else f"执行未完成：{outcome.code}",
                    )
                async with transaction(self.database) as db:
                    await runs.finish(db, context, outcome)
                if identity is not None:
                    metadata = (
                        runtime.trace_metadata if isinstance(runtime, GuardedRuntime) else None
                    )
                    await self._trace(context, identity, metadata)
            except Exception as error:
                self.persistence_failures.add(context.run_id)
                # 数据库错误正文可能含条件/连接信息，只保留异常类型与标准SQLSTATE定位。
                kind, sqlstate = database_error_details(error)
                LOGGER.error(
                    "TaskRun persistence failed: %s error=%s sqlstate=%s",
                    context.run_id,
                    kind,
                    sqlstate,
                )
            finally:
                self.cancelled.pop(context.run_id, None)
                self.tasks.pop(context.run_id, None)

    async def _trace(
        self, context: RunContext, identity: RuntimeIdentity, metadata: TraceMetadata | None = None
    ) -> None:
        """仅从已提交事件导出脱敏Trace；失败不能覆盖业务终态。"""
        try:
            recorded: list[RuntimeEvent] = []
            after = 0
            while rows := await self.events(context.user_id, context.run_id, after):
                recorded.extend(TypeAdapter(list[RuntimeEvent]).validate_python(rows))
                after = int(str(rows[-1]["sequence"]))
            path = (
                self.trace_directory
                / str(context.user_id)
                / str(context.session_id)
                / f"{context.run_id}.jsonl"
            )
            await asyncio.to_thread(
                write_trace,
                path,
                recorded,
                identity,
                metadata=metadata,
                trace_cloud=self.trace_cloud,
            )
        except Exception:
            LOGGER.warning("TaskRun Trace unavailable: %s", context.run_id)

    async def close(self) -> None:
        for event in self.cancelled.values():
            event.set()
        await asyncio.gather(*tuple(self.tasks.values()), return_exceptions=True)

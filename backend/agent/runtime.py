"""应用执行入口：检查会话归属，调用 runtime，发布唯一终态；不编排模型循环。"""

import asyncio
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from backend.domain.execution import (
    RunContext,
    RunResult,
    RuntimeEvent,
    RuntimeIdentity,
    RuntimeOutcome,
    SessionReference,
    terminal_event,
)

type EventSink = Callable[[RuntimeEvent], None]


class Runtime(Protocol):
    identity: RuntimeIdentity

    async def execute(
        self,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome: ...


class Agent:
    """首版进程内引用表；M2.4 才实现数据库与 SDK 文件的跨进程恢复。"""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self._references: dict[UUID, SessionReference] = {}
        self._active: set[tuple[UUID, UUID]] = set()

    async def run(
        self,
        context: RunContext,
        prompt: str,
        emit: EventSink,
        *,
        reference_id: UUID | None = None,
        cancelled: asyncio.Event | None = None,
    ) -> RunResult:
        runtime, identity = self.runtime, self.runtime.identity
        key = (context.user_id, context.session_id)
        reference = self._references.get(reference_id) if reference_id else None
        if reference_id and (reference is None or not self._owns(reference, context)):
            return self._finish(
                context, RuntimeOutcome(code="blocked", reason="unknown_session"), emit, identity
            )
        if key in self._active:
            return self._finish(
                context, RuntimeOutcome(code="conflict", reason="session_busy"), emit, identity
            )
        if not prompt.strip():
            return self._finish(
                context, RuntimeOutcome(code="validation", reason="empty_prompt"), emit, identity
            )
        # 不变量：换模型/供应商/版本时重新建立 SDK 会话，绝不重放旧原始消息。
        sdk_id = reference.sdk_session_id if reference and reference.identity == identity else None
        self._active.add(key)
        try:
            emit(RuntimeEvent(context, "started"))
            try:
                outcome = await runtime.execute(
                    context, prompt, sdk_id, emit, cancelled or asyncio.Event()
                )
            except asyncio.CancelledError:
                outcome = RuntimeOutcome(code="cancelled", reason="cancelled")
            except Exception:
                outcome = RuntimeOutcome(code="provider_error", reason="runtime_failure")
            return self._finish(context, outcome, emit, identity)
        finally:
            # 中断也使旧引用失效；不能假设 SDK 已完整保存上一轮工具结果。
            if reference_id:
                self._references.pop(reference_id, None)
            self._active.remove(key)

    def _finish(
        self,
        context: RunContext,
        outcome: RuntimeOutcome,
        emit: EventSink,
        identity: RuntimeIdentity,
    ) -> RunResult:
        reference = None
        if outcome.code is None and not outcome.sdk_session_id:
            outcome = RuntimeOutcome(code="provider_error", reason="missing_session")
        if outcome.code is None:
            assert outcome.sdk_session_id is not None
            reference = SessionReference(context, identity, outcome.sdk_session_id)
            self._references[reference.id] = reference
        emit(terminal_event(context, outcome))
        return RunResult(context, outcome, reference)

    @staticmethod
    def _owns(reference: SessionReference, context: RunContext) -> bool:
        return (reference.context.user_id, reference.context.session_id) == (
            context.user_id,
            context.session_id,
        )


class FakeRuntime:
    """预设应用事件和结果的离线替身；不模拟 SDK 内部循环或声称模型效果。"""

    identity = RuntimeIdentity("fake", "scripted", "none", "none")

    def __init__(self, outcome: RuntimeOutcome, text: tuple[str, ...] = ()) -> None:
        self.outcome, self.text = outcome, text
        self.resumed: list[str | None] = []

    async def execute(
        self,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        self.resumed.append(sdk_session_id)
        if cancelled.is_set():
            return RuntimeOutcome(code="cancelled", reason="cancelled")
        for text in self.text:
            emit(RuntimeEvent(context, "text", text=text))
        return self.outcome

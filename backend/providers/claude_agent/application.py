"""API调用已验证的隔离live入口；只桥接事件和取消，不再实现模型工具循环。"""

import asyncio
import importlib.metadata
import os
from pathlib import Path
from threading import Event

from pydantic import TypeAdapter, ValidationError

from backend.agent.runtime import EventSink
from backend.domain.execution import (
    RunContext,
    RunResult,
    RuntimeEvent,
    RuntimeIdentity,
    RuntimeOutcome,
    error_code,
)
from backend.providers.claude_agent.live import run_live
from backend.providers.claude_agent.settings import model_name, provider_name
from backend.providers.probe.settings import ProbeError


class GuardedRuntime:
    def __init__(self, root: Path, database_dsn: str) -> None:
        self.root, self.database_dsn = root, database_dsn
        provider = provider_name(os.environ)
        self.identity = RuntimeIdentity(
            provider,
            model_name(os.environ, provider),
            importlib.metadata.version("claude-agent-sdk"),
            "reported-by-worker",
        )

    async def execute(
        self,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        if sdk_session_id is not None:
            return RuntimeOutcome(code="blocked", reason="business_resume_not_verified")
        if cancelled.is_set():
            return RuntimeOutcome(code="cancelled", reason="cancelled")
        stop = Event()
        loop = asyncio.get_running_loop()

        def forward(event: RuntimeEvent) -> None:
            # 外层Agent产生唯一started/终态；worker同类事件仍保留在私有运行证据中。
            if event.kind in {
                "text",
                "tool_started",
                "tool_finished",
                "presentation",
                "context_compacted",
            }:
                loop.call_soon_threadsafe(emit, event)

        operation = asyncio.create_task(
            asyncio.to_thread(
                run_live,
                prompt,
                context,
                self.root,
                database_dsn=self.database_dsn,
                emit=forward,
                cancelled=stop,
                max_attempts=12,
            )
        )
        watcher = asyncio.create_task(cancelled.wait())
        try:
            done, _ = await asyncio.wait((operation, watcher), return_when=asyncio.FIRST_COMPLETED)
            if watcher in done:
                stop.set()
            report = await asyncio.shield(operation)
            if cancelled.is_set():
                return RuntimeOutcome(code="cancelled", reason="cancelled")
            return outcome(report, context)
        except asyncio.CancelledError:
            stop.set()
            # 费用结算和自有进程清理必须结束；清理期间的错误不覆盖用户取消。
            await asyncio.shield(asyncio.gather(operation, return_exceptions=True))
            return RuntimeOutcome(code="cancelled", reason="cancelled")
        except ProbeError as error:
            return RuntimeOutcome(code=error_code(error.code), reason="live_unavailable")
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


def outcome(report: dict[str, object], context: RunContext) -> RuntimeOutcome:
    if report.get("status") != "success":
        return RuntimeOutcome(code=error_code(report.get("code")), reason="live_failed")
    results = report.get("results")
    if not isinstance(results, list) or len(results) != 1:
        return RuntimeOutcome(code="provider_error", reason="invalid_live_result")
    try:
        result = TypeAdapter(RunResult).validate_python(results[0])
    except ValidationError:
        return RuntimeOutcome(code="provider_error", reason="invalid_live_result")
    if result.context != context:
        return RuntimeOutcome(code="blocked", reason="live_identity_mismatch")
    return result.outcome

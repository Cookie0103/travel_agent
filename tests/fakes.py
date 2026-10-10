"""测试用 Runtime 替身。"""

import asyncio

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeIdentity, RuntimeOutcome


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

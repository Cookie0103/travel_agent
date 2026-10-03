"""默认离线演示：固定调用两个真实只读工具，不把确定性脚本冒充模型自主规划。"""

import asyncio
from uuid import uuid4

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeIdentity, RuntimeOutcome
from backend.tools.contracts import ToolExecutor


class FixtureRuntime:
    identity = RuntimeIdentity("fake", "fixture-demo", "none", "none")

    def __init__(self, executor: ToolExecutor) -> None:
        self.executor = executor

    async def execute(
        self,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        city = "东京" if "东京" in prompt or "tokyo" in prompt.casefold() else "京都"
        indoor = "室内" in prompt or "雨" in prompt
        rows: list[str] = ["离线演示：固定调用景点和攻略工具；数据为人工测试集。"]
        for name, collection in (("search_places", "places"), ("search_content", "articles")):
            if cancelled.is_set():
                return RuntimeOutcome(code="cancelled", reason="cancelled")
            arguments: dict[str, object] = {
                "city": city,
                "query": "室内" if indoor else "",
                "limit": 3,
            }
            if name == "search_places" and indoor:
                arguments["indoor"] = True
            call_id = uuid4()
            emit(
                RuntimeEvent(
                    context,
                    "tool_started",
                    tool_name=name,
                    tool_call_id=call_id,
                    argument_keys=tuple(sorted(arguments)),
                )
            )
            result = await self.executor.execute(context, name, arguments)
            emit(
                RuntimeEvent(
                    context,
                    "tool_finished",
                    tool_name=name,
                    code=result.code,
                    tool_call_id=call_id,
                    result_empty=result.empty,
                )
            )
            if result.code:
                return RuntimeOutcome(code=result.code, reason="tool_failed")
            items = result.data.get(collection)
            if not isinstance(items, list):
                return RuntimeOutcome(code="provider_error", reason="invalid_tool_result")
            if not items:
                rows.append(f"{city}：没有匹配的{collection}数据。")
            for item in items:
                if isinstance(item, dict):
                    label = item.get("name", item.get("title", ""))
                    rows.append(f"- {label}（来源：{item.get('source_ref')}；fixture）")
        text = "\n".join(rows)
        emit(RuntimeEvent(context, "text", text=text))
        return RuntimeOutcome(text, sdk_session_id or str(uuid4()))

"""默认离线演示：固定脚本调用真实业务工具，不把脚本冒充模型自主规划。"""

import asyncio
from uuid import uuid4

from backend.agent.demo import demo_command
from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeIdentity, RuntimeOutcome
from backend.tools.contracts import ToolExecutor
from backend.tools.execution import execute_observed
from backend.tools.search import DEFINITIONS


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
        if prompt.startswith("演示："):
            return await demo_command(self.executor, context, prompt, emit, cancelled)
        city = "东京" if "东京" in prompt or "tokyo" in prompt.casefold() else "京都"
        indoor = "室内" in prompt or "雨" in prompt
        rows: list[str] = ["离线演示：固定调用景点和攻略工具，不代表模型自主规划。"]
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
            definition = next(item for item in DEFINITIONS if item.name == name)
            result = await execute_observed(
                self.executor, context, name, arguments, emit, definition=definition
            )
            if result.code:
                return RuntimeOutcome(code=result.code, reason="tool_failed")
            items = result.data.get(collection)
            if not isinstance(items, list):
                return RuntimeOutcome(code="provider_error", reason="invalid_tool_result")
            if not items:
                rows.append(f"{city}：没有匹配的{collection}数据。")
            label_mode = "人工测试集" if result.data_mode == "fixture" else "历史快照，非实时事实"
            for item in items:
                if isinstance(item, dict):
                    label = item.get("name", item.get("title", ""))
                    source = item.get("source")
                    ref = (
                        source.get("source_ref")
                        if isinstance(source, dict)
                        else item.get("source_ref")
                    )
                    rows.append(f"- {label}（来源：{ref}；{result.data_mode}，{label_mode}）")
        text = "\n".join(rows)
        emit(RuntimeEvent(context, "text", text=text))
        return RuntimeOutcome(text, sdk_session_id or str(uuid4()))

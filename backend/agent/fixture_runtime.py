"""默认离线演示：固定脚本调用真实业务工具，不把脚本冒充模型自主规划。"""

import asyncio
import re
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.agent.demo import demo_command
from backend.agent.fixture_conditions import (
    ambiguous_expression,
    fixture_patch,
    missing_question,
    unsupported_trip_currency,
)
from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeIdentity, RuntimeOutcome
from backend.tools.contracts import ToolExecutor
from backend.tools.execution import execute_observed
from backend.tools.search import DEFINITIONS
from backend.tools.travel import DEFINITIONS as TRAVEL_DEFINITIONS
from backend.tools.travel import TravelToolExecutor


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
        if isinstance(self.executor, TravelToolExecutor):
            request = await self.executor.travel.get_request(context)
            if unsupported_trip_currency(prompt):
                text = (
                    "全程预算目前只支持日元，离线演示未更新任何条件。"
                    "请明确日元金额；住宿预算可保留原币种，不换汇。"
                )
                emit(RuntimeEvent(context, "text", text=text))
                return RuntimeOutcome(text, sdk_session_id or str(uuid4()))
            if ambiguous_expression(prompt):
                text = (
                    "这句包含假设或否定，离线演示未更新任何条件。"
                    "请明确说出要保存的新值，或继续提问。"
                )
                emit(RuntimeEvent(context, "text", text=text))
                return RuntimeOutcome(text, sdk_session_id or str(uuid4()))
            patch = fixture_patch(prompt, request, datetime.now(ZoneInfo("Asia/Tokyo")).date())
            if patch["set"] or patch["clear"]:
                if cancelled.is_set():
                    return RuntimeOutcome(code="cancelled", reason="cancelled")
                definition = next(
                    d for d in TRAVEL_DEFINITIONS if d.name == "update_travel_request"
                )
                result = await execute_observed(
                    self.executor,
                    context,
                    "update_travel_request",
                    patch,
                    emit,
                    definition=definition,
                )
                request = await self.executor.travel.get_request(context)
                if result.code:
                    text = "离线演示未更新条件，请确认本次信息：" + (
                        result.suggestion or "条件格式无效。"
                    )
                else:
                    message = result.data.get("message")
                    text = "离线演示：有限表达提取，不调用模型。\n" + (
                        message if isinstance(message, str) else ""
                    )
                    relation = result.data.get("budget_relation")
                    if isinstance(relation, dict) and relation.get("status") == "conflict":
                        text += "\n" + str(relation["message"])
                    else:
                        text += "\n" + missing_question(request)
                emit(RuntimeEvent(context, "text", text=text))
                return RuntimeOutcome(text, sdk_session_id or str(uuid4()))
            # 查询样例可用明确城市；其他未识别表达追问，不注入京都默认值。
            if not re.search(r"室内|雨|景点|攻略|文章|查询|推荐", prompt):
                text = "离线演示未识别本次新条件。" + missing_question(request)
                emit(RuntimeEvent(context, "text", text=text))
                return RuntimeOutcome(text, sdk_session_id or str(uuid4()))
            city_match = re.search(r"札幌|京都|东京|東京|大阪|名古屋|福冈|横滨", prompt)
            city = city_match[0].replace("東京", "东京") if city_match else request.city
            if not city:
                text = "离线演示仅识别有限旅行表达。" + missing_question(request)
                emit(RuntimeEvent(context, "text", text=text))
                return RuntimeOutcome(text, sdk_session_id or str(uuid4()))
        else:
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

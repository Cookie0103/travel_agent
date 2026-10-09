"""两个只读旅行工具的共享输入/schema与业务查询；先使用明确标记的本地 fixtures。"""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from backend.domain.catalog import ContentSearchInput, PlaceSearchInput, search
from backend.domain.execution import RunContext
from backend.tools.contracts import ToolDefinition, ToolResult

__all__ = ["ContentSearchInput", "PlaceSearchInput", "search", "SearchExecutor", "DEFINITIONS"]

DEFINITIONS = (
    ToolDefinition(
        "search_places",
        "查询景点属性与来源，营业时间缺失时为未知。无主题时query用空字符串，城市只填city；优先一次limit=8取候选，有够用证据就规划，不逐景点重复搜索。",
        PlaceSearchInput.model_json_schema(),
    ),
    ToolDefinition(
        "search_content",
        "查询攻略段落及引用；测试数据不能当实时事实。",
        ContentSearchInput.model_json_schema(),
    ),
)
FIXTURE = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "kyoto.json"


def load_fixture(path: Path = FIXTURE) -> dict[str, list[dict[str, object]]]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("测试数据格式错误")
    result: dict[str, list[dict[str, object]]] = {}
    for key in ("places", "articles"):
        rows = value.get(key)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("测试数据缺少集合")
        result[key] = [{str(k): v for k, v in row.items()} for row in rows]
    return result


class SearchExecutor:
    """固定只读注册表；API/MCP/离线演示共用参数验证和错误语义。"""

    def __init__(
        self,
        loader: Callable[[], dict[str, list[dict[str, object]]]] = load_fixture,
        *,
        timeout_seconds: float = 5,
        max_calls: int = 12,
    ) -> None:
        self.loader, self.timeout_seconds, self.max_calls = loader, timeout_seconds, max_calls
        self.definitions = {d.name: d for d in DEFINITIONS}
        self.calls = 0

    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        collection = {"search_places": "places", "search_content": "articles"}.get(name)
        if collection is None:
            return ToolResult({}, code="blocked", suggestion="请选择已注册的旅行工具")
        definition = self.definitions[name]
        try:
            input_type = PlaceSearchInput if name == "search_places" else ContentSearchInput
            parsed = input_type.model_validate(arguments)
        except ValidationError:
            return ToolResult(
                {}, code="validation", suggestion="检查城市、筛选条件和 limit；不接受身份参数"
            )
        if self.calls >= self.max_calls:
            return ToolResult({}, code="blocked", suggestion="本轮工具次数已达上限")
        self.calls += 1
        try:
            async with asyncio.timeout(min(self.timeout_seconds, definition.timeout_seconds)):
                data = await asyncio.to_thread(self.loader)
                rows = search(data[collection], parsed)
        except TimeoutError:
            return ToolResult({}, code="timeout", suggestion="稍后重试数据查询")
        except (OSError, ValueError, KeyError):
            return ToolResult({}, code="unavailable", suggestion="检查本地数据文件")
        if len(json.dumps(rows, ensure_ascii=False)) > definition.max_result_chars:
            return ToolResult({}, code="blocked", suggestion="缩小查询范围")
        return ToolResult(
            {collection: rows}, empty=not rows, warnings=("人工测试数据，非实时事实；营业时间未知",)
        )

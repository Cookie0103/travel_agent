"""R01：旅行查询成功、空结果与失败使用同一工具契约，数据来源不能消失。"""

import asyncio
import time
from pathlib import Path
from uuid import uuid4

import pytest

from backend.agent.fixture_runtime import FixtureRuntime
from backend.agent.runtime import Agent
from backend.domain.execution import RunContext
from backend.tools.contracts import ToolResult
from backend.tools.search import SearchExecutor, load_fixture


@pytest.mark.asyncio
async def test_places_and_content_keep_fixture_provenance() -> None:
    executor = SearchExecutor()
    context = RunContext(uuid4())
    for name, key in (("search_places", "places"), ("search_content", "articles")):
        result = await executor.execute(
            context, name, {"city": "Kyoto", "query": "室内", "limit": 3}
        )
        assert result.payload()["status"] == "ok"
        rows = result.data[key]
        assert isinstance(rows, list) and 1 <= len(rows) <= 3
        assert all(
            row["source_ref"].startswith("fixture:") and row["data_mode"] == "fixture"
            for row in rows
        )
    fixture = load_fixture()
    assert len(fixture["places"]) == 20 and len(fixture["articles"]) == 12


@pytest.mark.asyncio
async def test_city_filter_and_alias_search_are_deterministic() -> None:
    executor, context = SearchExecutor(), RunContext(uuid4())
    absent = await executor.execute(context, "search_places", {"city": "东京"})
    found = await executor.execute(context, "search_places", {"city": "京都", "query": "金阁寺"})
    assert absent.payload()["status"] == "empty" and absent.code is None
    assert "鹿苑寺" in str(found.data)
    assert "opening_hours': None" in str(found.data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"city": "京都", "user_id": "forged"},
        {"city": "京都", "limit": True},
        {"city": "京都", "limit": 100},
    ],
)
async def test_invalid_input_does_not_touch_loader(arguments: dict[str, object]) -> None:
    def forbidden() -> dict[str, list[dict[str, object]]]:
        raise AssertionError("must not load")

    result = await SearchExecutor(forbidden).execute(
        RunContext(uuid4()), "search_places", arguments
    )
    assert result.code == "validation"


@pytest.mark.asyncio
async def test_unknown_tool_missing_data_and_call_limit_fail_safely(tmp_path: Path) -> None:
    context = RunContext(uuid4())
    executor = SearchExecutor(lambda: load_fixture(tmp_path / "missing"), max_calls=1)
    unknown = await executor.execute(context, "Bash", {})
    missing = await executor.execute(context, "search_places", {"city": "京都"})
    exhausted = await executor.execute(context, "search_places", {"city": "京都"})
    assert (unknown.code, missing.code, exhausted.code) == ("blocked", "unavailable", "blocked")


@pytest.mark.asyncio
async def test_offline_demo_runs_tools_and_labels_fixture() -> None:
    result = await Agent(FixtureRuntime(SearchExecutor())).run(
        RunContext(uuid4()), "京都有哪些室内景点？", lambda e: None
    )
    assert result.outcome.code is None and "fixture:kyoto-v1" in result.outcome.text
    assert "fixture:kyoto-guide-v1" in result.outcome.text and "人工测试集" in result.outcome.text
    cancelled = asyncio.Event()
    cancelled.set()
    outcome = await FixtureRuntime(SearchExecutor()).execute(
        RunContext(uuid4()), "问", None, lambda e: None, cancelled
    )
    assert outcome.code == "cancelled"


@pytest.mark.asyncio
async def test_slow_and_oversized_data_returns_explicit_failure() -> None:
    def slow() -> dict[str, list[dict[str, object]]]:
        time.sleep(0.05)
        return load_fixture()

    def huge() -> dict[str, list[dict[str, object]]]:
        return {"places": [{"city": "京都", "name": "x" * 9000}]}

    context = RunContext(uuid4())
    timed = await SearchExecutor(slow, timeout_seconds=0.01).execute(
        context, "search_places", {"city": "京都"}
    )
    large = await SearchExecutor(huge).execute(context, "search_places", {"city": "京都"})
    assert timed.code == "timeout" and large.code == "blocked"


@pytest.mark.asyncio
async def test_article_schema_only_accepts_supported_filters() -> None:
    executor, context = SearchExecutor(), RunContext(uuid4())
    invalid = await executor.execute(context, "search_content", {"city": "京都", "indoor": True})
    category = await executor.execute(
        context, "search_content", {"city": "京都", "category": "museum"}
    )
    assert invalid.code == "validation"
    assert category.code is None and not category.empty and "漫画" in str(category.data)


@pytest.mark.asyncio
async def test_offline_query_uses_chinese_labels_and_preserves_original_names() -> None:
    class NamedExecutor:
        async def execute(
            self, context: RunContext, name: str, arguments: dict[str, object]
        ) -> ToolResult:

            key = "places" if name == "search_places" else "articles"
            return ToolResult({key: [{"name": "京都東急ホテル", "source_ref": "fixture:jp-name"}]})

    outcome = await FixtureRuntime(NamedExecutor()).execute(
        RunContext(uuid4()), "京都景点", None, lambda e: None, asyncio.Event()
    )
    assert outcome.text.count("京都東急ホテル") == 2
    assert "fixture:jp-name；人工测试集" in outcome.text
    assert "；fixture，" not in outcome.text


@pytest.mark.asyncio
async def test_offline_empty_query_categories_are_chinese() -> None:
    outcome = await FixtureRuntime(SearchExecutor(lambda: {"places": [], "articles": []})).execute(
        RunContext(uuid4()), "京都景点", None, lambda e: None, asyncio.Event()
    )
    assert "没有匹配的景点数据" in outcome.text
    assert "没有匹配的攻略文章数据" in outcome.text
    assert "places" not in outcome.text and "articles" not in outcome.text

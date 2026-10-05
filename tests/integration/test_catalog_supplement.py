"""R03/R05：独立真实PG的补充目录、Evidence隔离及实际SDK工具往返。"""

import asyncio
import hashlib
import json
import shutil
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import TypeAdapter
from sqlalchemy import URL

from backend.domain.execution import RunResult, RuntimeEvent
from backend.mcp.bridge import sdk_tool_name
from backend.persistence.catalog import import_catalog, load_catalog
from backend.persistence.temporary import temporary_database
from backend.services.common import ServiceError, transaction
from backend.tools.fencing import fence
from backend.tools.travel import TravelToolExecutor
from data.import_catalog import load_snapshot
from eval.database import DATA_VERSION, DatabaseEvaluation, database_evaluation, selector_runner
from eval.graders import Observation, grade
from eval.run import ROOT, run_cases
from eval.suites import load_suite
from tests.integration.sdk_helper import run_database_worker
from tests.test_catalog_supplement import SUPPLEMENT
from tests.test_sdk_cli_offline import scripted_response

pytestmark = pytest.mark.integration


@pytest.fixture
def curated_business(postgres_url: URL) -> Iterator[tuple[asyncio.Runner, DatabaseEvaluation]]:
    # 不变量：补充目录不进入所有integration共享的原快照测试库。
    with temporary_database(postgres_url, "test") as target, selector_runner() as runner:
        manager = database_evaluation(target, catalog_dir=SUPPLEMENT)
        business = runner.run(manager.__aenter__())
        try:
            yield runner, business
        finally:
            runner.run(manager.__aexit__(None, None, None))


def test_curated_import_queries_preserve_sources_unknowns_and_evidence_ownership(
    curated_business: tuple[asyncio.Runner, DatabaseEvaluation], tmp_path: Path
) -> None:
    runner, business = curated_business
    cases, _ = load_suite(ROOT, "legacy", "dev")
    case = next(c for c in cases if c.case_id == "kyoto-matcha")

    async def exercise() -> None:
        context, other = [await business.prepare(case) for _ in range(2)]
        executor = TravelToolExecutor(business.travel)
        article = await executor.execute(
            context, "search_content", {"city": "京都", "query": "抹茶"}
        )
        place = await executor.execute(
            context, "search_places", {"city": "京都", "query": "都路里"}
        )
        assert article.code is None and place.code is None and not article.empty and not place.empty
        records = await business.travel.resolve_evidence(
            context, [UUID(e) for e in place.evidence_ids]
        )
        assert len(records) == 1 and records[0].content_version is not None
        assert records[0].content_version.endswith(":curation-v1")
        assert isinstance(records[0].value, dict)
        assert records[0].value["opening_hours"] is None and records[0].value["indoor"] is None
        with pytest.raises(ServiceError) as denied:
            await business.travel.resolve_evidence(other, [records[0].evidence_id])
        assert denied.value.status == 404
        assert (await executor.execute(context, "search_places", {"city": "大阪"})).empty
        assert (
            await executor.execute(context, "search_content", {"city": "京都", "limit": 0})
        ).code == "validation"
        async with transaction(business.sessions.database) as db:
            await import_catalog(db, load_snapshot(SUPPLEMENT))
            await import_catalog(db, load_snapshot(SUPPLEMENT))
            rows = await load_catalog(db)
        assert {key: len(value) for key, value in rows.items()} == {"places": 1, "articles": 1}
        digest = hashlib.sha256((SUPPLEMENT / "manifest.json").read_bytes()).hexdigest()
        assert (
            business.data_version == f"catalog-sha256:{digest}+hotel-fixture-v1+routes-fixture-v1"
        )
        assert business.data_version != DATA_VERSION
        await run_cases([case], tmp_path / "report", business=business)
        for filename in ("manifest.json", "summary.json"):
            metadata = json.loads((tmp_path / "report" / filename).read_text(encoding="utf-8"))
            assert metadata["data_version"] == business.data_version

    runner.run(exercise())


def test_selected_catalog_mismatch_keeps_existing_data(
    curated_business: tuple[asyncio.Runner, DatabaseEvaluation],
) -> None:
    runner, business = curated_business
    url = business.sessions.database.engine.url

    async def exercise() -> None:
        async with transaction(business.sessions.database) as db:
            original = await load_catalog(db)
        with pytest.raises(ServiceError) as rejected:
            async with database_evaluation(url):
                raise AssertionError("original snapshot cannot accept a different catalog")
        assert rejected.value.status == 409
        async with transaction(business.sessions.database) as db:
            assert await load_catalog(db) == original

    runner.run(exercise())


@pytest.mark.skipif(not shutil.which("claude"), reason="需要本机Claude CLI，不访问真实模型")
def test_actual_sdk_matches_original_two_search_tool_contract_on_curated_sources(
    curated_business: tuple[asyncio.Runner, DatabaseEvaluation], tmp_path: Path
) -> None:
    runner, business = curated_business
    cases, _ = load_suite(ROOT, "legacy", "dev")
    case = next(c for c in cases if c.case_id == "kyoto-matcha")
    context = runner.run(business.prepare(case))
    calls: tuple[tuple[str, dict[str, object]], ...] = (
        (sdk_tool_name("search_content"), {"city": "京都", "query": "抹茶"}),
        (sdk_tool_name("search_places"), {"city": "京都", "query": "都路里"}),
    )
    report, guard = run_database_worker(
        business.travel, context, tmp_path, partial(scripted_response, tool_calls=calls), case.input
    )
    assert report["status"] == "success" and not guard.failures
    assert guard.attempts == 2
    results = TypeAdapter(list[RunResult]).validate_python(report["results"])
    events = TypeAdapter(tuple[RuntimeEvent, ...]).validate_python(report["events"])
    text = results[-1].outcome.text
    assert all(grade(case, Observation("completed", text, events)).values())
    payloads = [json.loads(block["text"]) for content in json.loads(text) for block in content]
    assert len(payloads) == 2 and all(p["status"] == "ok" for p in payloads)
    article = next(p["data"]["articles"][0] for p in payloads if "articles" in p["data"])
    place = next(p["data"]["places"][0] for p in payloads if "places" in p["data"])
    assert place["name"] == fence("茶寮都路里") and place["source"]["content_version"].endswith(
        ":curation-v1"
    )
    assert article["source"]["source_ref"].startswith("https://en.wikivoyage.org/")
    assert {e.tool_name for e in events if e.kind == "tool_started"} == set(case.allowed_tools)

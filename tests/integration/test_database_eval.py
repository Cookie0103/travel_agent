"""M3.4：PG评测身份/条件隔离、持久开始记录、真实SDK固定流程及依赖故障。"""

import asyncio
import hashlib
import json
import shutil
import socket
from dataclasses import asdict
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from sqlalchemy import URL, delete

from backend.domain.catalog import Place
from backend.domain.execution import RunContext, RunResult
from backend.persistence.catalog import import_catalog, load_catalog
from backend.persistence.models import CatalogRow
from backend.services.common import ServiceError, transaction
from backend.services.sessions import SessionService
from backend.services.travel import TravelService
from backend.tools.travel import DEFINITIONS
from backend.tools.workflow import WorkflowName
from data.import_catalog import load_snapshot
from eval.cases import Case
from eval.database import DATA_VERSION, DatabaseEvaluation, database_evaluation, selector_runner
from eval.run import run_cases
from tests.integration.sdk_helper import run_database_worker
from tests.integration.test_sdk_hotels import hotel_response
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def search_case(**changes: object) -> Case:
    return Case.model_validate(
        {
            "case_id": "database-search",
            "source": "self-authored mechanism test",
            "adaptation": "not model quality",
            "input": "京都室内景点",
            "required_tools": ["search_places", "search_content"],
            "allowed_tools": ["search_places", "search_content"],
            "should_have_results": True,
            "initial_state": {"request": {"city": "京都", "adults": 2}},
            **changes,
        }
    )


@pytest.mark.parametrize("query,passed", [("京都景点", 1), ("京都室内景点", 0)])
def test_database_eval_separates_case_state_and_uses_actual_application_tools(
    postgres_url: URL,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    passed: int,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("offline evaluation must not access models")

    monkeypatch.setattr("eval.run.run_live", forbidden)

    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            contexts = [await business.prepare(search_case()) for _ in range(2)]
            assert contexts[0].user_id != contexts[1].user_id
            assert contexts[0].session_id != contexts[1].session_id
            for context in contexts:
                request = await business.travel.get_request(context)
                assert request.city == "京都" and request.adults == 2 and request.revision == 1
            for workflow in (None, "search"):
                directory = tmp_path / (workflow or "autonomous")
                summary = await run_cases(
                    [search_case(input=query)], directory, business=business, workflow=workflow
                )
                assert summary["passed"] == passed
                assert summary["errors"] == int(not passed and workflow == "search")
                assert summary["mode"] == "offline_database_fixture"
                assert summary["data_version"] == DATA_VERSION
                row = json.loads((directory / "results.jsonl").read_text(encoding="utf-8"))
                assert row["tool_count"] == 2 and row["http_attempts"] == 0
                assert row["tokens"] is None and row["run_accounted_cny"] is None
                if passed:
                    assert "历史快照" in row["text"]
                else:
                    assert "has_results" in row["failed_checks"]
                metadata = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
                expected = hashlib.sha256(
                    json.dumps([asdict(d) for d in DEFINITIONS], sort_keys=True).encode()
                ).hexdigest()
                assert metadata["schema_sha256"] == expected
                assert metadata["skills"] == ["hotel-comparison", "itinerary-revision"]
                assert metadata["catalog_sha256"] == business.catalog_sha256
                assert business.catalog_sha256
                assert "DATABASE_URL" not in str(metadata)

    with selector_runner() as runner:
        runner.run(exercise())


def test_database_live_attempt_has_actual_pg_identity_before_model_and_stops_on_failure(
    postgres_url: URL, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "live-result"
    calls: list[RunContext] = []

    def synthetic_failure(
        prompt: str, context: RunContext, root: Path, **kwargs: object
    ) -> dict[str, object]:
        started = json.loads((directory / "attempts.jsonl").read_text(encoding="utf-8"))
        assert started["context"]["user_id"] == str(context.user_id)
        assert started["context"]["session_id"] == str(context.session_id)
        assert kwargs["workflow"] == "hotel" and kwargs["max_attempts"] == 6
        assert isinstance(kwargs["database_dsn"], str)
        calls.append(context)
        return {"status": "error", "http_attempts": 0}

    monkeypatch.setattr("eval.run.run_live", synthetic_failure)

    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            summary = await run_cases(
                [search_case(), search_case(case_id="second")],
                directory,
                live=True,
                business=business,
                workflow="hotel",
                max_attempts=6,
            )
            assert len(calls) == 1 and summary["errors"] == 1 and summary["not_run"] == 1
            assert (await business.travel.get_request(calls[0])).adults == 2
            assert summary["rule_pass_rate"] is None

    with selector_runner() as runner:
        runner.run(exercise())


@pytest.mark.parametrize("state", [{"unknown": True}, {"request": {"adults": True}}])
def test_invalid_database_initial_state_never_calls_model(
    postgres_url: URL, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: dict[str, object]
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("invalid conditions must stop before models")

    monkeypatch.setattr("eval.run.run_live", forbidden)

    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            summary = await run_cases(
                [search_case(initial_state=state)],
                tmp_path / "result",
                live=True,
                business=business,
            )
            assert summary["errors"] == 1 and summary["evaluated"] == 0
            assert (tmp_path / "result" / "attempts.jsonl").read_text(encoding="utf-8") == ""

    with selector_runner() as runner:
        runner.run(exercise())


def test_database_unavailable_reports_setup_error_without_retry(
    postgres_url: URL, tmp_path: Path
) -> None:
    async def exercise(url: URL) -> None:
        business = DatabaseEvaluation(url)
        try:
            summary = await run_cases([search_case()], tmp_path / "result", business=business)
            assert summary["errors"] == 1
            row = json.loads((tmp_path / "result" / "results.jsonl").read_text(encoding="utf-8"))
            assert row["reason"] == "business_setup_failed"
            assert "password" not in str(row)
        finally:
            await business.sessions.close()

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        with selector_runner() as runner:
            runner.run(exercise(postgres_url.set(port=listener.getsockname()[1])))


@pytest.mark.skipif(not shutil.which("claude"), reason="需要实际CLI，不访问真实模型")
@pytest.mark.parametrize("workflow", [None, "hotel"])
def test_same_real_sdk_and_database_tools_run_both_ordering_modes(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
    workflow: WorkflowName | None,
) -> None:
    runner, travel, context = travel_setup
    schemas: list[list[str]] = []

    def forward(body: bytes) -> tuple[int, bytes]:
        request = json.loads(body)
        schemas.append(sorted(t["name"] for t in request["tools"]))
        return hotel_response(body)

    report, guard = run_database_worker(
        travel, context, tmp_path, forward, "比较两个模拟酒店的含税总价", workflow=workflow
    )
    assert report["status"] == "success", (report.get("code"), guard.failures)
    assert guard.attempts == 3 and not guard.failures
    assert all(schema == schemas[0] and len(schema) == len(DEFINITIONS) for schema in schemas)
    events = report["events"]
    assert isinstance(events, list)
    assert [e["tool_name"] for e in events if e["kind"] == "tool_finished"] == [
        "search_hotel_offers",
        "present_travel_result",
    ]
    assert all(e["code"] is None for e in events if e["kind"] == "tool_finished")
    presentations = [e["presentation"] for e in events if e["kind"] == "presentation"]
    assert len(presentations) == 1 and "lowest_offer_ids" in str(presentations)
    assert (runner.run(travel.get_request(context))).revision == 1
    results = TypeAdapter(list[RunResult]).validate_python(report["results"])
    assert results[0].context.user_id == context.user_id


def test_eval_rejects_catalog_drift_without_overwriting_or_deleting_it(postgres_url: URL) -> None:
    async def exercise() -> None:
        sessions = SessionService(postgres_url)
        entries = load_snapshot()
        extra = next(entry for entry in entries if isinstance(entry, Place)).model_copy(
            update={"place_id": "fixture:eval-owned-extra"}
        )
        try:
            async with transaction(sessions.database) as db:
                await import_catalog(db, entries)
                await import_catalog(db, [extra])
            with pytest.raises(ServiceError) as error:
                async with database_evaluation(postgres_url):
                    raise AssertionError("catalog drift cannot reach model evaluation")
            assert error.value.code == "conflict"
            async with transaction(sessions.database) as db:
                actual = await load_catalog(db)
                assert any(
                    row["place_id"] == "fixture:eval-owned-extra" for row in actual["places"]
                )
        finally:
            async with transaction(sessions.database) as db:
                await db.execute(
                    delete(CatalogRow).where(CatalogRow.id == "fixture:eval-owned-extra")
                )
            await sessions.close()

    with selector_runner() as runner:
        runner.run(exercise())

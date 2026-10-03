"""每个评测案例创建独立业务会话；复用应用PG服务、快照与旅行工具。"""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict

from sqlalchemy import URL

from backend.agent.fixture_runtime import FixtureRuntime
from backend.agent.runtime import Agent
from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.travel_request import RequestPatch
from backend.persistence.catalog import import_catalog, load_catalog
from backend.services.common import ServiceError, transaction
from backend.services.sessions import DemoLogin, SessionService
from backend.services.travel import TravelService
from backend.tools.contracts import ToolExecutor
from backend.tools.travel import TravelToolExecutor
from backend.tools.workflow import OrderedTools, WorkflowName
from data.import_catalog import load_snapshot
from eval.cases import Case, InitialState
from eval.graders import Observation

DATA_VERSION = "kyoto-snapshot-v1+hotel-fixture-v1+routes-fixture-v1"


class DatabaseEvaluation:
    def __init__(self, url: URL) -> None:
        if url.host not in {"127.0.0.1", "localhost"} or url.query:
            raise ValueError("业务评测只使用本地项目PostgreSQL")
        self.sessions = SessionService(url, demo_enabled=True)
        self.travel = TravelService(self.sessions.database)
        self.catalog_sha256: str | None = None

    async def prepare(self, case: Case) -> RunContext:
        if case.fault or case.data_version != "kyoto-fixture-v1":
            raise ValueError("尚不支持此评测故障或数据版本")
        conditions = InitialState.model_validate(case.initial_state).request
        identity = await self.sessions.create_demo_user(DemoLogin(display_name="本地评测"))
        session = await self.sessions.new_session(identity.user_id)
        context = RunContext(identity.user_id, session.session_id)
        fields = conditions.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        if fields:
            await self.travel.patch_request(
                context, RequestPatch.model_validate({"expected_revision": 0, "set": fields})
            )
        return context

    async def observe(
        self, case: Case, context: RunContext, workflow: WorkflowName | None
    ) -> tuple[Observation, dict[str, object]]:
        executor: ToolExecutor = TravelToolExecutor(self.travel)
        if workflow:
            executor = OrderedTools(executor, workflow)
        runtime = FixtureRuntime(executor)
        events: list[RuntimeEvent] = []
        result = await Agent(runtime).run(context, case.input, events.append)
        return Observation(
            "failed" if result.outcome.code else "completed", result.outcome.text, tuple(events)
        ), {"identity": asdict(runtime.identity), "data_version": DATA_VERSION}

    def dsn(self) -> str:
        return self.sessions.database.engine.url.render_as_string(hide_password=False)


@asynccontextmanager
async def database_evaluation(url: URL) -> AsyncIterator[DatabaseEvaluation]:
    evaluation = DatabaseEvaluation(url)
    try:
        await evaluation.sessions.health()
        entries = load_snapshot()
        expected: dict[str, list[dict[str, object]]] = {"places": [], "articles": []}
        for entry in entries:
            payload = entry.model_dump(mode="json")
            kind = "places" if "place_id" in payload else "articles"
            expected[kind].append(payload)
        for kind, rows in expected.items():
            rows.sort(key=lambda row: str(row["place_id" if kind == "places" else "article_id"]))
        async with transaction(evaluation.sessions.database) as db:
            actual = await load_catalog(db)
            if not any(actual.values()):
                await import_catalog(db, entries)
                actual = await load_catalog(db)
            if actual != expected:
                raise ServiceError(409, "conflict", "评测目录与版本化快照不一致，不覆盖现有数据")
            evaluation.catalog_sha256 = hashlib.sha256(
                json.dumps(actual, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
        yield evaluation
    finally:
        await evaluation.sessions.close()


def selector_runner() -> asyncio.Runner:
    """评测父进程只操作PG；SDK仍由既有隔离worker使用Proactor。"""
    return asyncio.Runner(loop_factory=asyncio.SelectorEventLoop)

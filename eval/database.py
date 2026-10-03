"""每个评测案例创建独立业务会话；复用应用PG服务、快照与旅行工具。"""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import URL, select

from backend.adapters.local_http import serve_http
from backend.adapters.supplier import SupplierClient
from backend.agent.fixture_runtime import FixtureRuntime
from backend.agent.runtime import Agent
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.travel_request import RequestPatch
from backend.persistence import travel
from backend.persistence.catalog import import_catalog, load_catalog
from backend.persistence.database import Database
from backend.persistence.models import EvidenceRow
from backend.services.common import ServiceError, transaction
from backend.services.sessions import DemoLogin, SessionService
from backend.services.travel import TravelService, request_from_row
from backend.tools.contracts import ToolExecutor
from backend.tools.travel import TravelToolExecutor
from backend.tools.workflow import OrderedTools, WorkflowName
from data.import_catalog import SNAPSHOT, load_snapshot
from eval.business_metrics import BusinessAssessment
from eval.cases import Case, InitialState
from eval.content import AnswerRecord, Grounding
from eval.graders import Observation
from eval.state import StateSnapshot, assess_business, prepare_state, snapshot
from mock_supplier.scenarios import SupplierScenario

DATA_VERSION = "kyoto-snapshot-v1+hotel-fixture-v1+routes-fixture-v1"


class DatabaseEvaluation:
    def __init__(self, url: URL) -> None:
        if url.host not in {"127.0.0.1", "localhost"} or url.query:
            raise ValueError("业务评测只使用本地项目PostgreSQL")
        self.sessions = SessionService(url, demo_enabled=True)
        self.travel = TravelService(self.sessions.database)
        self.catalog_sha256: str | None = None
        self.data_version = DATA_VERSION
        self.supplier_url: str | None = None
        self.scenario: SupplierScenario | None = None
        self.baselines: dict[UUID, StateSnapshot] = {}

    async def prepare(self, case: Case) -> RunContext:
        if case.data_version != "kyoto-fixture-v1":
            raise ValueError("尚不支持此评测数据版本")
        state = InitialState.model_validate(case.initial_state)
        if (state.booking != "none" or case.fault) and not self.supplier_url:
            raise ValueError("预订/故障评测需要专用本机供应商")
        if self.scenario:
            self.scenario.fault = None
        conditions = state.request
        identity = await self.sessions.create_demo_user(DemoLogin(display_name="本地评测"))
        session = await self.sessions.new_session(identity.user_id)
        context = RunContext(identity.user_id, session.session_id)
        fields = conditions.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        if fields:
            await self.travel.patch_request(
                context, RequestPatch.model_validate({"expected_revision": 0, "set": fields})
            )
        await prepare_state(
            self.travel, context, state, self.supplier_url or "http://127.0.0.1:8001"
        )
        context = replace(context, run_id=uuid4())
        self.baselines[context.run_id] = await snapshot(self.travel, context)
        if self.scenario:
            self.scenario.fault = case.fault
            self.scenario.attempts.clear()
        return context

    async def checks(self, case: Case, context: RunContext, actual: Observation) -> dict[str, bool]:
        return (await self.assess(case, context, actual)).checks

    async def assess(
        self, case: Case, context: RunContext, actual: Observation
    ) -> BusinessAssessment:
        return await assess_business(
            self.travel,
            context,
            case,
            self.baselines[context.run_id],
            actual.events,
            tuple(self.scenario.attempts) if self.scenario else (),
        )

    async def content_record(self, case: Case, context: RunContext, text: str) -> AnswerRecord:
        """在临时库清理前捕获身份限定事实；旧/失效证据也保留以识别错引用。"""
        async with transaction(self.sessions.database) as db:
            request = request_from_row(await travel.owned_request(db, context))
            rows = await db.scalars(
                select(EvidenceRow).where(
                    EvidenceRow.user_id == context.user_id,
                    EvidenceRow.session_id == context.session_id,
                )
            )
            return AnswerRecord(
                case_id=case.case_id,
                context=context,
                request=request,
                observed_at=datetime.now(UTC),
                text=text,
                evidence=tuple(
                    Grounding(
                        context=context,
                        record=EvidenceRecord.model_validate(row.payload),
                        invalidated=row.invalidated,
                    )
                    for row in rows
                ),
            )

    async def observe(
        self, case: Case, context: RunContext, workflow: WorkflowName | None
    ) -> tuple[Observation, dict[str, object]]:
        travel_executor = TravelToolExecutor(self.travel)
        if self.supplier_url:
            travel_executor.bookings.supplier = SupplierClient(self.supplier_url)
        executor: ToolExecutor = travel_executor
        if workflow:
            executor = OrderedTools(executor, workflow)
        runtime = FixtureRuntime(executor)
        events: list[RuntimeEvent] = []
        result = await Agent(runtime).run(context, case.input, events.append)
        return Observation(
            "failed" if result.outcome.code else "completed", result.outcome.text, tuple(events)
        ), {"identity": asdict(runtime.identity), "data_version": self.data_version}

    def dsn(self) -> str:
        return self.sessions.database.engine.url.render_as_string(hide_password=False)


@asynccontextmanager
async def database_evaluation(
    url: URL, *, supplier: bool = False, catalog_dir: Path | None = None
) -> AsyncIterator[DatabaseEvaluation]:
    evaluation = DatabaseEvaluation(url)
    try:
        await evaluation.sessions.health()
        folder = catalog_dir if catalog_dir is not None else SNAPSHOT
        entries = load_snapshot(folder)
        if catalog_dir is not None:
            digest = hashlib.sha256((folder / "manifest.json").read_bytes()).hexdigest()
            evaluation.data_version = f"catalog-sha256:{digest}+hotel-fixture-v1+routes-fixture-v1"
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
        if supplier:
            evaluation.scenario = SupplierScenario(Database(url))
            with serve_http(evaluation.scenario.app) as endpoint:
                evaluation.supplier_url = endpoint
                yield evaluation
        else:
            yield evaluation
    finally:
        await evaluation.sessions.close()


def selector_runner() -> asyncio.Runner:
    """评测父进程只操作PG；SDK仍由既有隔离worker使用Proactor。"""
    return asyncio.Runner(loop_factory=asyncio.SelectorEventLoop)

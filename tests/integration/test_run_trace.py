"""R12/R17：实际PG事件导出与写盘故障隔离，不以Trace替代业务事实。"""

import asyncio
import json
import shutil
from collections.abc import Callable, Mapping
from decimal import Decimal
from functools import partial
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request, Response
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from backend.adapters.local_http import serve_http
from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.mcp.bridge import sdk_tool_name
from backend.providers.claude_agent import application, live
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import worker_environment
from backend.providers.claude_agent.guard import Forward, Guard
from backend.providers.claude_agent.limits import Settings
from backend.services.runs import MessageInput, RunService
from backend.services.travel import TravelService
from backend.tools.contracts import ToolExecutor
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS
from tests.fakes import FakeRuntime
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_sdk_cli_offline import scripted_response

pytestmark = pytest.mark.integration


class PatchRuntime(FakeRuntime):
    def __init__(self, executor: ToolExecutor) -> None:
        super().__init__(RuntimeOutcome())
        self.executor = executor

    async def execute(
        self,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        result = await execute_observed(
            self.executor,
            context,
            "update_travel_request",
            {"expected_revision": 1, "set": {"interests": [prompt]}},
            emit,
            definition=next(d for d in DEFINITIONS if d.name == "update_travel_request"),
        )
        return RuntimeOutcome(text=prompt, sdk_session_id="fixture", code=result.code)


@pytest.mark.parametrize("disk_failure", [False, True])
def test_committed_run_exports_metadata_or_preserves_result_on_disk_failure(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    disk_failure: bool,
) -> None:
    runner, travel, context = travel_setup
    directory = tmp_path / "traces"
    if disk_failure:
        directory.write_text("blocked", encoding="utf-8")
    service = RunService(travel.database, runtime_factory=PatchRuntime, trace_directory=directory)
    private_text = "私人喜好，不能出现在Trace全文中"

    async def exercise() -> None:
        created = await service.submit(
            context.user_id,
            context.session_id,
            MessageInput(client_message_id=uuid4(), text=private_text),
        )
        await asyncio.gather(*tuple(service.tasks.values()))
        final = await service.get(context.user_id, created.run_id)
        assert final.status == "completed" and final.answer == private_text
        assert (await travel.get_request(context)).revision == 2
        assert not service.tasks and not service.persistence_failures
        path = (
            directory / str(context.user_id) / str(context.session_id) / f"{created.run_id}.jsonl"
        )
        if disk_failure:
            assert "TaskRun Trace unavailable" in caplog.text
            assert private_text not in caplog.text
            return
        raw = path.read_text(encoding="utf-8")
        assert private_text not in raw
        spans = [json.loads(line) for line in raw.splitlines()]
        root = next(s for s in spans if s["name"] == "travel.run")
        tool = next(s for s in spans if s["name"] == "tool.update_travel_request")
        assert root["attributes"]["travel.run_id"] == str(created.run_id)
        assert root["attributes"]["travel.status"] == "completed"
        assert tool["attributes"]["travel.request_revision"] == 2
        assert tool["attributes"]["tool.argument_keys"] == ["expected_revision", "set"]
        assert tool["attributes"]["tool.status"] == "ok"
        events = await service.events(context.user_id, created.run_id, 0)
        assert events[-1]["kind"] == "completed"
        assert [e["sequence"] for e in events] == [1, 2, 3, 4]

    runner.run(exercise())


@pytest.mark.skipif(not shutil.which("claude"), reason="需要实际CLI，不访问真实模型")
@pytest.mark.parametrize("upstream_failure", [False, True])
def test_api_actual_sdk_usage_reaches_committed_trace_and_otlp(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    upstream_failure: bool,
) -> None:
    """R17：真实SDK/守卫/PG/API与本机OTLP，成功/上游失败费用均不伪造。"""
    runner, travel, context = travel_setup
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    monkeypatch.setattr(
        live,
        "load_runtime_settings",
        lambda env: Settings("offline-only", "deepseek-flash", Decimal(5), Decimal(0)),
    )
    guards: list[Guard] = []

    def guard(
        settings: Settings,
        budget: Budget,
        forward: Forward,
        *,
        allowed_tools: frozenset[str],
        max_attempts: int = 4,
    ) -> Guard:
        # 签名/实例不变，保留本轮实际守卫以逐字段核对观测。
        result = Guard(
            settings,
            budget,
            forward,
            allowed_tools=allowed_tools,
            max_attempts=max_attempts,
        )
        guards.append(result)
        return result

    monkeypatch.setattr(live, "Guard", guard)

    def environment(
        source: Mapping[str, str],
        directory: Path,
        root: Path,
        endpoint: str,
        token: str,
        model: str,
    ) -> dict[str, str]:
        # 临时目录只放私有账本/会话，worker仍从本仓库载入真实实现。
        return worker_environment(
            source, directory, Path(__file__).resolve().parents[2], endpoint, token, model
        )

    monkeypatch.setattr(live, "worker_environment", environment)
    forward = partial(
        scripted_response, tool_calls=((sdk_tool_name("load_skill"), {"name": "hotel-comparison"}),)
    )
    calls = 0

    def local_model(provider: str, key: str, body: bytes) -> tuple[int, bytes]:
        nonlocal calls
        assert provider == "deepseek"
        assert key == "offline-only"
        calls += 1
        return (
            (503, b"synthetic-private-upstream-error")
            if upstream_failure and calls == 2
            else forward(body)
        )

    monkeypatch.setattr(live, "forward_messages", local_model)
    collector = FastAPI()
    received: list[ExportTraceServiceRequest] = []

    @collector.post("/api/public/otel/v1/traces")
    async def collect(request: Request) -> Response:
        received.append(ExportTraceServiceRequest.FromString(await request.body()))
        return Response(status_code=200)

    with serve_http(collector) as base:
        monkeypatch.setenv("LANGFUSE_BASE_URL", base)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "local-public")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "local-secret")
        runtime = application.GuardedRuntime(
            tmp_path, travel.database.engine.url.render_as_string(hide_password=False)
        )
        initial = runtime.identity
        service = RunService(
            travel.database,
            live_enabled=True,
            runtime_factory=lambda e: runtime,
            trace_directory=tmp_path / "api",
            trace_cloud=True,
        )

        async def exercise() -> None:
            created = await service.submit(
                context.user_id,
                context.session_id,
                MessageInput(
                    client_message_id=uuid4(), text="synthetic-private-prompt", mode="deepseek"
                ),
            )
            await asyncio.wait_for(asyncio.gather(*tuple(service.tasks.values())), timeout=40)
            final = await service.get(context.user_id, created.run_id)
            assert final.status == ("failed" if upstream_failure else "completed")
            assert not service.persistence_failures and not service.tasks
            assert (await travel.get_request(context)).revision == 1
            assert runtime.identity is initial and runtime.trace_metadata is not None
            metadata = runtime.trace_metadata
            assert metadata.identity.cli_version != "reported-by-worker"
            assert len(guards) == 1 and calls == guards[0].attempts == 2
            assert (
                len(metadata.requests)
                == len(guards[0].observations)
                == (1 if upstream_failure else 2)
            )
            assert metadata.accounted == guards[0].budget.totals()[1]
            path = (
                tmp_path
                / "api"
                / str(context.user_id)
                / str(context.session_id)
                / f"{created.run_id}.jsonl"
            )
            raw = path.read_text(encoding="utf-8")
            assert all(
                s not in raw
                for s in [
                    "synthetic-private-prompt",
                    "local-secret",
                    "synthetic-private-upstream-error",
                ]
            )
            local = [json.loads(line) for line in raw.splitlines()]
            sdk = next(s for s in local if s["name"] == "agent.sdk")["attributes"]
            assert sdk["travel.cli_version"] == metadata.identity.cli_version
            assert sdk["travel.http_attempts"] == 2
            assert sdk["travel.usage_complete"] is (not upstream_failure)
            assert sdk["travel.unobserved_responses"] == (1 if upstream_failure else 0)
            assert sdk["travel.run_accounted_cny"] == str(metadata.accounted)
            assert sdk["gen_ai.usage.output_tokens"] == sum(
                int(str(r["output_tokens"])) for r in metadata.requests
            )
            assert sdk["travel.model_subcalls_observed"] is False
            stored = await service.events(context.user_id, created.run_id, 0)
            assert stored[-1]["kind"] == final.status
            spans = [
                s
                for item in received
                for r in item.resource_spans
                for scope in r.scope_spans
                for s in scope.spans
            ]
            assert len(received) == 1 and len(spans) == len(local)
            assert {s.trace_id.hex() for s in spans} == {
                s["context"]["trace_id"].removeprefix("0x") for s in local
            }
            cloud_sdk = next(s for s in spans if s.name == "agent.sdk")
            attrs = {a.key: a.value for a in cloud_sdk.attributes}
            assert attrs["travel.cli_version"].string_value == metadata.identity.cli_version
            assert attrs["travel.http_attempts"].int_value == 2
            assert attrs["travel.run_accounted_cny"].string_value == str(metadata.accounted)
            assert attrs["travel.usage_complete"].bool_value is (not upstream_failure)

        runner.run(exercise())


@pytest.mark.parametrize(
    "enabled,response_status,delayed",
    [
        (False, 200, False),
        (True, 200, False),
        (True, 400, False),
        (True, None, False),
        (True, 200, True),
    ],
)
def test_cloud_trace_is_explicit_and_failure_preserves_committed_run_and_local_trace(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    enabled: bool,
    response_status: int | None,
    delayed: bool,
) -> None:
    """R17：真实PG与OTLP HTTP；缺配置/拒绝/3秒读超时不能撤销业务。"""
    import base64

    runner, travel, context = travel_setup
    collector = FastAPI()
    received: list[ExportTraceServiceRequest] = []
    closed: list[OTLPSpanExporter] = []
    original_shutdown: Callable[[OTLPSpanExporter], None] = OTLPSpanExporter.shutdown

    def shutdown(exporter: OTLPSpanExporter) -> None:
        closed.append(exporter)
        original_shutdown(exporter)

    monkeypatch.setattr(OTLPSpanExporter, "shutdown", shutdown)

    @collector.post("/api/public/otel/v1/traces")
    async def collect(request: Request) -> Response:
        expected = base64.b64encode(b"local-public:local-secret").decode()
        assert request.headers["authorization"] == "Basic " + expected
        assert request.headers["x-langfuse-ingestion-version"] == "4"
        body = await request.body()
        assert b"local-secret" not in body and b"synthetic-private-interest" not in body
        received.append(ExportTraceServiceRequest.FromString(body))
        if delayed:
            await asyncio.sleep(5)
        return Response(status_code=response_status or 400)

    with serve_http(collector) as base_url:
        for name, value in {
            "LANGFUSE_BASE_URL": base_url,
            "LANGFUSE_PUBLIC_KEY": "local-public",
            "LANGFUSE_SECRET_KEY": "local-secret",
        }.items():
            monkeypatch.setenv(name, value)
        if response_status is None:
            monkeypatch.delenv("LANGFUSE_SECRET_KEY")
        directory = tmp_path / "traces"
        service = RunService(
            travel.database,
            runtime_factory=PatchRuntime,
            trace_directory=directory,
            trace_cloud=enabled,
        )

        async def exercise() -> None:
            created = await service.submit(
                context.user_id,
                context.session_id,
                MessageInput(client_message_id=uuid4(), text="synthetic-private-interest"),
            )
            started = perf_counter()
            await asyncio.wait_for(asyncio.gather(*tuple(service.tasks.values())), timeout=10)
            if delayed:
                assert 2.5 <= perf_counter() - started < 10
            final = await service.get(context.user_id, created.run_id)
            assert final.status == "completed" and final.error_code is None
            assert final.answer == "synthetic-private-interest"
            assert (await travel.get_request(context)).revision == 2
            assert not service.tasks and not service.persistence_failures
            path = directory / str(context.user_id) / str(context.session_id)
            raw = (path / f"{created.run_id}.jsonl").read_text(encoding="utf-8")
            assert "synthetic-private-interest" not in raw and "local-secret" not in raw
            local = [json.loads(line) for line in raw.splitlines()]
            assert {s["name"] for s in local} == {
                "travel.run",
                "agent.fixture",
                "tool.update_travel_request",
            }
            if enabled and response_status == 200 and not delayed:
                spans = [
                    span
                    for item in received
                    for resource in item.resource_spans
                    for scope in resource.scope_spans
                    for span in scope.spans
                ]
                assert len(received) == 1 and len(spans) == len(local)
                assert {s.trace_id.hex() for s in spans} == {
                    s["context"]["trace_id"].removeprefix("0x") for s in local
                }
                assert "TaskRun Trace unavailable" not in caplog.text
            else:
                assert len(received) == (
                    1 if enabled and (response_status == 400 or delayed) else 0
                )
                assert ("TaskRun Trace unavailable" in caplog.text) == enabled
            assert "local-secret" not in caplog.text
            assert "synthetic-private-interest" not in caplog.text
            assert len(closed) == (1 if enabled and response_status is not None else 0)

        runner.run(exercise())

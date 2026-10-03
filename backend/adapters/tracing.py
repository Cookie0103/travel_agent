"""将真实应用事件映射为 OTel spans；默认本地文件，显式配置才导出到 Langfuse。"""

import base64
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import Span, StatusCode, Tracer, set_span_in_context
from pydantic import TypeAdapter

from backend.domain.execution import RuntimeEvent, RuntimeIdentity


def trace_report(
    report: dict[str, object], directory: Path, exporter: SpanExporter | None = None
) -> None:
    """私有工作报告已有事件/版本信息；不从正文推断工具或虚构缺失时间。"""
    if not report.get("events") or not report.get("identity"):
        report["trace_status"] = "unavailable_events"
        return
    try:
        raw = TypeAdapter(list[dict[str, object]]).validate_python(report["events"])
        if any("occurred_at" not in event for event in raw):
            raise ValueError("记录缺少真实事件时间")
        events = TypeAdapter(list[RuntimeEvent]).validate_python(report["events"])
        if report.get("status") == "error" and events[-1].kind == "completed":
            events.append(
                RuntimeEvent(
                    events[-1].context,
                    "failed",
                    code="provider_error",
                    occurred_at=events[-1].occurred_at,
                )
            )
        identity = TypeAdapter(RuntimeIdentity).validate_python(report["identity"])
        requests = TypeAdapter(list[dict[str, object]]).validate_python(report.get("requests", []))
        attempts = report.get("http_attempts")
        if attempts is not None and (type(attempts) is not int or attempts < len(requests)):
            raise ValueError("Trace 请求次数不完整")
        charge = report.get("run_accounted_cny")
        report["trace_id"] = write_trace(
            directory / "trace.jsonl",
            events,
            identity,
            requests=requests,
            exporter=exporter,
            http_attempts=attempts if isinstance(attempts, int) else None,
            accounted_cny=Decimal(str(charge)) if charge is not None else None,
        )
    except (OSError, ValueError, ArithmeticError, KeyError):
        # 不变量：可观测性失败不能抹掉业务结果；异常正文可能包含私有路径或原始数据。
        report.update(trace_status="failed", trace_error="unavailable")
        return
    report["trace_status"] = "local_saved_cloud_sent" if exporter is not None else "local_saved"


def cloud_exporter(environment: Mapping[str, str]) -> SpanExporter:
    """仅由显式 --trace-cloud 调用，不读取通用 OTEL_* 隐式配置。"""
    base = environment.get("LANGFUSE_BASE_URL", "").strip().rstrip("/")
    public = environment.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = environment.get("LANGFUSE_SECRET_KEY", "").strip()
    url = urlsplit(base)
    if (
        not public
        or not secret
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Langfuse URL/public key/secret key 未完整配置")
    if url.scheme != "https" and not (
        url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost"}
    ):
        raise ValueError("Langfuse 仅允许 HTTPS 或本机 HTTP")
    encoded = base64.b64encode(f"{public}:{secret}".encode()).decode()
    return OTLPSpanExporter(
        endpoint=base + "/api/public/otel/v1/traces",
        headers={"Authorization": "Basic " + encoded, "x-langfuse-ingestion-version": "4"},
        timeout=3,
    )


def write_trace(
    path: Path,
    events: Sequence[RuntimeEvent],
    identity: RuntimeIdentity,
    *,
    requests: Sequence[Mapping[str, object]] = (),
    exporter: SpanExporter | None = None,
    http_attempts: int | None = None,
    accounted_cny: Decimal | None = None,
) -> str:
    """用 SDK exporter 输出 JSONL，时长取自事件，不使用导出时长冒充执行时长。"""
    if not events or len({e.context.run_id for e in events}) != 1:
        raise ValueError("Trace 需要一轮实际运行的事件")
    if any(e.occurred_at.tzinfo is None for e in events):
        raise ValueError("Trace 时间必须带时区")
    path.parent.mkdir(parents=True, exist_ok=True)
    provider = TracerProvider(
        resource=Resource({"service.name": "travel-agent"}),
        sampler=ALWAYS_ON,
        shutdown_on_exit=False,
    )
    try:
        memory = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(memory))
        tracer = provider.get_tracer("travel-agent")
        trace_id = _spans(tracer, events, identity, requests, http_attempts, accounted_cny)
        spans = memory.get_finished_spans()
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            local = ConsoleSpanExporter(out=handle, formatter=_format_span)
            if local.export(spans) != SpanExportResult.SUCCESS:
                raise OSError("本地 Trace 导出失败")
        if exporter is not None and exporter.export(spans) != SpanExportResult.SUCCESS:
            raise OSError("云端 Trace 导出失败；本地记录已保留")
        return trace_id
    finally:
        provider.shutdown()
        if exporter is not None:
            exporter.shutdown()


def _format_span(span: ReadableSpan) -> str:
    value: object = span.to_json(indent=None)
    if not isinstance(value, str):
        raise TypeError("OTel exporter 未返回 JSON 文本")
    return value + "\n"


def _ns(event: RuntimeEvent) -> int:
    return int(event.occurred_at.timestamp() * 1_000_000_000)


def _spans(
    tracer: Tracer,
    events: Sequence[RuntimeEvent],
    identity: RuntimeIdentity,
    requests: Sequence[Mapping[str, object]],
    http_attempts: int | None,
    accounted_cny: Decimal | None,
) -> str:
    attributes: dict[str, str | bool] = {
        "travel.run_id": str(events[0].context.run_id),
        "travel.provider": identity.provider,
        "gen_ai.request.model": identity.model,
        "travel.sdk_version": identity.sdk_version,
        "travel.cli_version": identity.cli_version,
        "travel.mode": "offline" if identity.provider == "fake" else "live",
        "travel.model_subcalls_observed": False,
    }
    root = tracer.start_span("travel.run", start_time=_ns(events[0]), attributes=attributes)
    runtime = tracer.start_span(
        "agent.fixture" if identity.provider == "fake" else "agent.sdk",
        context=set_span_in_context(root),
        start_time=_ns(events[0]),
        attributes=attributes,
    )
    _usage(runtime, requests, http_attempts, accounted_cny)
    incomplete = _tool_spans(tracer, runtime, events)
    end = events[-1]
    for span in (runtime, root):
        span.set_attribute(
            "travel.status",
            end.kind if end.kind in {"completed", "failed", "cancelled"} else "incomplete",
        )
        if end.kind != "completed" or incomplete:
            span.set_status(StatusCode.ERROR)
        span.end(end_time=_ns(end))
    return format(root.get_span_context().trace_id, "032x")


def _tool_spans(tracer: Tracer, parent: Span, events: Sequence[RuntimeEvent]) -> bool:
    active: dict[UUID, Span] = {}
    seen: set[UUID] = set()
    gap = False
    for event in events:
        if event.kind not in {"tool_started", "tool_finished"}:
            continue
        if event.tool_call_id is None or (
            event.kind == "tool_started" and event.tool_call_id in seen
        ):
            gap = True
            continue
        if event.kind == "tool_started" and event.tool_call_id is not None:
            seen.add(event.tool_call_id)
            active[event.tool_call_id] = tracer.start_span(
                "tool." + str(event.tool_name),
                context=set_span_in_context(parent),
                start_time=_ns(event),
                attributes={
                    "tool.name": str(event.tool_name),
                    "tool.call_id": str(event.tool_call_id),
                    "tool.argument_keys": event.argument_keys,
                },
            )
        elif event.kind == "tool_finished" and event.tool_call_id in active:
            span = active.pop(event.tool_call_id)
            span.set_attribute("tool.status", event.code or "ok")
            if event.code:
                span.set_status(StatusCode.ERROR)
            span.end(end_time=_ns(event))
        else:
            gap = True
    end = events[-1]
    for span in active.values():
        span.set_attribute("tool.status", "incomplete")
        span.set_status(StatusCode.ERROR)
        span.end(end_time=_ns(end))
    parent.set_attribute("travel.tool_events_complete", not (active or gap))
    return bool(active) or gap


def _usage(
    span: Span,
    requests: Sequence[Mapping[str, object]],
    http_attempts: int | None,
    accounted_cny: Decimal | None,
) -> None:
    span.set_attribute("travel.usage_observed", bool(requests))
    span.set_attribute("travel.usage_complete", http_attempts == len(requests))
    if http_attempts is not None:
        span.set_attribute("travel.http_attempts", http_attempts)
        span.set_attribute("travel.unobserved_responses", http_attempts - len(requests))
    if accounted_cny is not None:
        if not accounted_cny.is_finite() or accounted_cny < 0:
            raise ValueError("Trace 记账必须是有限非负值")
        span.set_attribute("travel.run_accounted_cny", str(accounted_cny))
    if not requests:
        return
    inputs = outputs = 0
    amount = Decimal(0)
    for request in requests:
        for key in (
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "output_tokens",
        ):
            value = request.get(key, 0)
            if type(value) is not int or value < 0:
                raise ValueError("Trace usage 不是已核验计数")
            if key == "output_tokens":
                outputs += value
            else:
                inputs += value
        charge = Decimal(str(request["usage_cost_upper_cny"]))
        if not charge.is_finite() or charge < 0:
            raise ValueError("Trace 费用必须是有限非负值")
        amount += charge
    span.set_attributes(
        {
            "gen_ai.usage.input_tokens": inputs,
            "gen_ai.usage.output_tokens": outputs,
            "travel.observed_cost_upper_cny": str(amount),
            "travel.accounted_responses": len(requests),
        }
    )

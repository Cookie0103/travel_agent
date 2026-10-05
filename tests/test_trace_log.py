"""TRACE日志：只含元数据、单行JSON、永不抛错；超时层与启动限额可从日志判别。"""

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
import pytest

from backend import server, trace_log
from backend.adapters.external_api import ApiUsage, request_json
from backend.domain.execution import RunContext
from backend.domain.external_data import ExternalDataError
from backend.providers.claude_agent import http
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.guard import Guard
from backend.providers.claude_agent.limits import Settings
from backend.tools.contracts import ToolDefinition, ToolResult
from backend.tools.execution import execute_observed
from backend.trace_log import FILE_ENV, RUN_ENV, Tail, trace
from tests.test_sdk_guard import request_body

SECRET = "sk-live-SECRET-123456"


@pytest.fixture(autouse=True)
def console_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trace_log, "_stdout", True)
    monkeypatch.delenv(FILE_ENV, raising=False)
    monkeypatch.delenv(RUN_ENV, raising=False)


def records(text: str) -> list[dict[str, object]]:
    lines = [line for line in text.splitlines() if line.startswith("TRACE ")]
    return [cast(dict[str, object], json.loads(line[6:])) for line in lines]


def test_trace_emits_one_valid_json_line_and_drops_secret_like_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    trace(
        "demo",
        "0123456789abcdef",
        elapsed_ms=12,
        api_key=SECRET,
        Authorization="Bearer " + SECRET,
        prompt="private prompt text",
        body={"messages": ["private"]},
        text="model output",
        url=f"https://x.example/v1?key={SECRET}",
        path=f"/v1/search?key={SECRET}",
        error_class="A" * 500,
        tools=["search_places", f"https://h/{SECRET}"],
        nested=object(),
    )
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and SECRET not in out and "private" not in out
    (record,) = records(out)
    assert record["run"] == "01234567" and record["ev"] == "demo" and record["elapsed_ms"] == 12
    assert record["path"] == "[redacted]" and record["tools"] == ["search_places"]
    assert record["api_key"] == record["prompt"] == record["body"] == "[dropped]"
    assert len(str(record["error_class"])) == 80 and str(record["ts"]).endswith("Z")


def test_trace_never_raises_when_stdout_or_file_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Broken:
        def write(self, _: str) -> int:
            raise OSError("closed")

        def flush(self) -> None:
            raise OSError("closed")

    monkeypatch.setattr(sys, "stdout", Broken())
    trace("still-fine", ok=1)
    monkeypatch.setenv(FILE_ENV, str(tmp_path / "missing" / "trace.jsonl"))
    trace("still-fine", ok=1)


def test_child_trace_file_is_relayed_only_when_line_is_complete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv(FILE_ENV, str(path))
    trace("worker_start", "abcdef012345")
    capsys.readouterr()
    assert path.read_text().startswith("TRACE ")  # 子进程写文件而不是stdout
    with path.open("a") as stream:
        stream.write('TRACE {"ev":"half')
    tail = Tail(path)
    tail.drain()
    assert [r["ev"] for r in records(capsys.readouterr().out)] == ["worker_start"]
    with path.open("a") as stream:
        stream.write('"}\n')
    tail.drain()
    assert [r["ev"] for r in records(capsys.readouterr().out)] == ["half"]
    Tail(tmp_path / "absent.jsonl").drain()  # 文件不存在也不抛错


@pytest.mark.parametrize(
    "profile,upstream,worker,ttl,rounds", [("human", 120, 840, 30, 50), ("", 90, 210, 15, 4)]
)
def test_boot_line_reports_effective_profile_limits(
    profile: str,
    upstream: int,
    worker: int,
    ttl: int,
    rounds: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TRAVEL_PROFILE", profile)
    server.log_boot()
    (record,) = records(capsys.readouterr().out)
    limits = cast(dict[str, object], record["limits"])
    assert record["ev"] == "boot" and record["profile"] == (profile or "default")
    assert limits["upstream_timeout"] == upstream and limits["worker_timeout"] == worker
    assert limits["evidence_ttl_minutes"] == ttl and limits["max_validations"] == rounds
    assert limits["live_tool_timeout"] == 75 and "run_timeout" in limits
    assert set(cast(dict[str, object], limits["run_caps"])) >= {"rakuten", "places"}


@pytest.mark.parametrize(
    "kind,layer", [("process", "upstream_process"), ("socket", "upstream_socket")]
)
def test_upstream_timeout_layer_is_identifiable_from_trace(
    kind: str,
    layer: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TRAVEL_PROFILE", "human")
    monkeypatch.setattr(http, "child_trace", (tmp_path / "child.jsonl", "abcdef01"))

    def stalled(
        args: list[str], cwd: Path, env: dict[str, str], timeout: float, input_text: str
    ) -> subprocess.CompletedProcess[str]:
        assert env[FILE_ENV] == str(tmp_path / "child.jsonl") and env[RUN_ENV] == "abcdef01"
        assert SECRET not in str(env)
        if kind == "process":
            raise subprocess.TimeoutExpired(args, timeout)
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"status": "error", "code": "timeout"}), ""
        )

    monkeypatch.setattr(http, "run_process", stalled)
    guard = Guard(
        Settings(SECRET, "deepseek-flash", Decimal(5), Decimal(0)),
        Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(5)),
        lambda body: http.forward_messages("deepseek", SECRET, body),
        run="abcdef01",
    )
    guard.accept("/v1/messages", "Bearer " + guard.token, request_body())
    out = capsys.readouterr().out
    events = {r["ev"]: r for r in records(out)}
    assert SECRET not in out and events["model_req_start"]["max_tokens"] == 1024
    assert events["timeout_fired"]["layer"] == layer
    assert events["timeout_fired"]["limit_s"] == (120 if kind == "process" else 115)
    assert events["model_req_end"]["error"] == "timeout"


@pytest.mark.asyncio
async def test_tool_timeout_is_logged_with_limit(capsys: pytest.CaptureFixture[str]) -> None:
    class Slow:
        async def execute(
            self, context: RunContext, name: str, arguments: dict[str, object]
        ) -> ToolResult:
            return ToolResult({}, code="timeout", suggestion="本轮工具执行超时")

    definition = ToolDefinition("search_hotel_offers", "d", {"type": "object"}, timeout_seconds=75)
    context = RunContext(uuid4())
    await execute_observed(
        Slow(), context, "search_hotel_offers", {"city": "private"}, lambda e: None,
        definition=definition,
    )  # fmt: skip
    out = capsys.readouterr().out
    start, end = records(out)
    assert start["ev"] == "tool_start" and end["ev"] == "tool_end" and "private" not in out
    assert end["timed_out"] is True and end["limit_s"] == 75 and end["code"] == "timeout"


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_api_call_logs_host_and_path_but_never_query_or_key(
    fail: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    class Usage(ApiUsage):
        def __init__(self) -> None:
            pass

        async def consume(self, api: str) -> None:
            return None

    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json={"hotels": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        call = request_json(
            client, Usage(), "rakuten", "GET", "https://api.example/v1/search",
            params={"applicationId": SECRET}, headers={"accessKey": SECRET},
        )  # fmt: skip
        if fail:
            with pytest.raises(ExternalDataError):
                await call
        else:
            await call
    out = capsys.readouterr().out
    (record,) = records(out)
    assert SECRET not in out and record["path"] == "/v1/search" and record["host"] == "api.example"
    assert record["ev"] == "api_call" and record["api"] == "rakuten"
    assert record["error_class"] == ("ReadTimeout" if fail else None)
    assert record["status"] == (None if fail else 200)


def test_budget_block_and_reserved_trace_numbers_and_guard_why(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from datetime import UTC, datetime

    from backend.providers.claude_agent.limits import ProbeError

    now = datetime(2026, 10, 5, 1, tzinfo=UTC)
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(5))
    budget.reserve(Decimal(3), now, "abcdef01")
    with pytest.raises(ProbeError, match="今日原币种余额不足"):
        budget.reserve(Decimal(3), now, "abcdef01")
    reserved, blocked = records(capsys.readouterr().out)
    assert reserved["ev"] == "budget_reserved" and reserved["run"] == "abcdef01"
    assert reserved["request_amount"] == "3" and reserved["daily_spent"] == "3"
    assert blocked["ev"] == "budget_block" and blocked["cause"] == "daily"
    assert blocked["day"] == "2026-10-05" and blocked["daily_spent"] == "3"
    assert blocked["request_amount"] == "3" and blocked["daily_limit"] == "5"
    assert blocked["entries_today"] == 1 and blocked["unsettled_today"] == 1
    assert blocked["currency"] == "CNY"

    guard = Guard(
        Settings(SECRET, "deepseek-flash", Decimal(5), Decimal(0)),
        Budget(tmp_path / "l2", tmp_path / "legacy", Decimal(5)),
        lambda body: (200, b""),
        run="abcdef01",
    )
    guard.failures.append("blocked")
    guard.accept("/v1/messages", "Bearer " + guard.token, request_body())
    end = records(capsys.readouterr().out)[-1]
    assert end["error"] == "blocked" and "请求上限" in str(end["why"])
    assert trace_log._clean("why", "a?b") == "[redacted]" and SECRET not in str(end)

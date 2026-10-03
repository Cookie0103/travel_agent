"""使用 SDK 自带 HTTP 依赖的 MockTransport，无网络验证流拼接与失败计费。"""

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest
from anthropic import DefaultHttpxClient
from anthropic.types import MessageParam

from backend.providers.probe.flow import tools_for_probe
from backend.providers.probe.ledger import Ledger
from backend.providers.probe.settings import ProbeError, Settings
from backend.providers.probe.transport import create_client, request

SETTINGS = Settings("synthetic-test-key", "deepseek-flash", Decimal("5"), Decimal("0"))
MESSAGES: list[MessageParam] = [{"role": "user", "content": "synthetic"}]


def stream_bytes(*, incomplete: bool = False) -> bytes:
    events: list[dict[str, object]] = [
        {
            "type": "message_start",
            "message": {
                "id": "test-message",
                "type": "message",
                "role": "assistant",
                "model": "deepseek-flash",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 12, "output_tokens": 0},
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "test-call",
                "name": "lookup_fixture",
                "input": {},
            },
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"ci'},
        },
    ]
    if not incomplete:
        events += [
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": 'ty":"Kyoto"}'},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 8},
            },
            {"type": "message_stop"},
        ]
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode("utf-8")


def test_stream_joins_json_fragments_and_sends_selected_model(tmp_path: Path) -> None:
    """R02：流内参数碎片拼成完整对象，模型选择从配置传到实际 HTTP 请求。"""
    captured: list[httpx2.Request] = []

    def handler(incoming: httpx2.Request) -> httpx2.Response:
        captured.append(incoming)
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=stream_bytes()
        )

    http = DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    settings = replace(SETTINGS, model="deepseek-v4-pro")
    ledger = Ledger(tmp_path / "ledger.jsonl")
    with create_client(settings, http_client=http) as client:
        assert client.max_retries == 0
        result = request(client, ledger, settings, MESSAGES, tools_for_probe())
    body = json.loads(captured[0].content)
    assert len(captured) == 1
    assert captured[0].url.host == "api.deepseek.com"
    assert body["model"] == "deepseek-v4-pro"
    assert body["max_tokens"] == 1024
    assert "message_stop" in result.events
    block = result.message.content[0]
    assert block.type == "tool_use" and block.input == {"city": "Kyoto"}
    assert ledger.entries()[0].charge == "0.20"


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "provider_error"),
        (401, "provider_error"),
        (429, "rate_limited"),
        (500, "provider_error"),
    ],
)
def test_http_failure_consumes_one_attempt_without_retry_or_body_leak(
    tmp_path: Path,
    status: int,
    code: str,
) -> None:
    calls: list[str] = []

    def handler(incoming: httpx2.Request) -> httpx2.Response:
        calls.append(incoming.method)
        return httpx2.Response(
            status, json={"error": {"type": "api_error", "message": "private-body"}}
        )

    http = DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    with create_client(SETTINGS, http_client=http) as client:
        with pytest.raises(ProbeError) as caught:
            request(client, ledger, SETTINGS, MESSAGES, tools_for_probe())
    assert caught.value.code == code
    assert "private-body" not in str(caught.value)
    assert calls == ["POST"]
    assert len(ledger.entries()) == 1
    assert ledger.entries()[0].charge == "0.05"


def test_timeout_is_not_treated_as_free_or_retried(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(incoming: httpx2.Request) -> httpx2.Response:
        calls.append(incoming.method)
        raise httpx2.ReadTimeout("private detail", request=incoming)

    http = DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    with create_client(SETTINGS, http_client=http) as client:
        with pytest.raises(ProbeError, match="timeout"):
            request(client, ledger, SETTINGS, MESSAGES, tools_for_probe())
    assert calls == ["POST"]
    assert len(Ledger(ledger.path).entries()) == 1


def test_insufficient_budget_blocks_before_http(tmp_path: Path) -> None:
    def handler(incoming: httpx2.Request) -> httpx2.Response:
        pytest.fail("HTTP must not start without enough CNY")

    http = DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    settings = replace(SETTINGS, cny_limit=Decimal("0.04"), usd_limit=Decimal("100"))
    with create_client(settings, http_client=http) as client:
        with pytest.raises(ProbeError, match="预算不足"):
            request(client, ledger, settings, MESSAGES, tools_for_probe())
    assert ledger.entries() == []


def test_failed_ledger_write_prevents_http(tmp_path: Path) -> None:
    def handler(incoming: httpx2.Request) -> httpx2.Response:
        pytest.fail("HTTP must not start when the ledger is unwritable")

    path = tmp_path / "not-a-directory"
    path.write_text("occupied", encoding="utf-8")
    ledger = Ledger(path / "ledger.jsonl")
    http = DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    with create_client(SETTINGS, http_client=http) as client:
        with pytest.raises(OSError):
            request(client, ledger, SETTINGS, MESSAGES, tools_for_probe())


def test_oversize_input_is_rejected_before_counting_or_http(tmp_path: Path) -> None:
    def handler(incoming: httpx2.Request) -> httpx2.Response:
        pytest.fail("oversize input must not start HTTP")

    ledger = Ledger(tmp_path / "ledger.jsonl")
    http = DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    with create_client(SETTINGS, http_client=http) as client:
        with pytest.raises(ProbeError, match="长度"):
            request(
                client,
                ledger,
                SETTINGS,
                [{"role": "user", "content": "x" * 9000}],
                tools_for_probe(),
            )
    assert ledger.entries() == []


def test_interrupted_stream_is_charged_and_never_returns_partial_message(tmp_path: Path) -> None:
    """R02：JSON 参数尚未完成且没有 message_stop 的流不能续接。"""

    def handler(incoming: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=stream_bytes(incomplete=True),
        )

    ledger = Ledger(tmp_path / "ledger.jsonl")
    http = DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    with create_client(SETTINGS, http_client=http) as client:
        with pytest.raises(ProbeError, match="provider_error"):
            request(client, ledger, SETTINGS, MESSAGES, tools_for_probe())
    assert len(ledger.entries()) == 1

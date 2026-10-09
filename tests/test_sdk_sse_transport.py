"""R17：完整SSE终态不等HTTP断开；不完整/超限仍保留预算。"""

import io
from decimal import Decimal
from http.client import HTTPResponse
from pathlib import Path
from socket import socket
from typing import cast

import pytest

from backend.limits import ProbeError, Settings
from backend.providers.claude_agent import http
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.guard import Guard
from backend.providers.claude_agent.request import validate_request
from backend.providers.claude_agent.response import summarize
from tests.test_sdk_guard import request_body, response_body


class OpenStream(io.BytesIO):
    """读尽已给出的chunk后模拟连接保持开启，不能靠EOF完成。"""

    def readline(self, size: int | None = -1) -> bytes:
        result = super().readline(size)
        if not result:
            raise TimeoutError("synthetic open connection")
        return result


def response(chunks: list[bytes]) -> HTTPResponse:
    wire = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + b"".join(
        f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n" for chunk in chunks
    )

    class Socket:
        def makefile(self, mode: str) -> OpenStream:
            return OpenStream(wire)

    result = HTTPResponse(cast(socket, Socket()))
    result.begin()
    return result


@pytest.mark.parametrize("split", [1, 7, 65536])
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_complete_stream_closes_at_terminal_without_waiting_for_http_eof(
    split: int, newline: bytes
) -> None:
    content = response_body().replace(b"\n", newline)
    stream = response([content[i : i + split] for i in range(0, len(content), split)])
    result = http._read_sse(stream)
    assert result == content
    assert (
        summarize(result, validate_request(request_body(), "deepseek-flash"), "deepseek-flash")[
            "stop_reason"
        ]
        == "end_turn"
    )


def test_old_full_body_read_waits_even_after_complete_sse() -> None:
    with pytest.raises(TimeoutError):
        response([response_body()]).read(http.MAX_RESPONSE_BYTES + 1)


def test_terminal_word_in_text_does_not_end_the_stream() -> None:
    content = b'data: {"type":"content_block_delta","delta":{"text":"message_stop"}}\n\n'
    with pytest.raises(TimeoutError):
        http._read_sse(response([content]))


@pytest.mark.parametrize(
    "content",
    [
        response_body(usage={}),
        response_body() + b'data: {"type":"message_stop"}\n\n',
        b'data: {"type":"message_stop"}\n\n',
    ],
)
def test_invalid_complete_stream_does_not_refund_or_retry(tmp_path: Path, content: bytes) -> None:
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(5))
    calls = 0

    def forward(body: bytes) -> tuple[int, bytes]:
        nonlocal calls
        calls += 1
        return 200, http._read_sse(response([content]))

    guard = Guard(Settings("offline", "deepseek-flash", Decimal(5), Decimal(0)), budget, forward)
    for _ in range(2):
        assert guard.accept("/v1/messages", "Bearer " + guard.token, request_body())[0] == 400
    assert calls == 1 and budget.totals()[0] == 1
    assert [entry.kind for entry in budget.entries()] == ["attempt"]


def test_partial_terminal_frame_still_waits_and_times_out() -> None:
    with pytest.raises(TimeoutError):
        http._read_sse(response([response_body().removesuffix(b"\n\n")]))


def test_stream_size_cap_is_checked_before_looking_for_terminal() -> None:
    with pytest.raises(ProbeError, match="超过"):
        http._read_sse(response([b"x" * (http.MAX_RESPONSE_BYTES + 1)]))

"""回环 HTTP 守卫连接 SDK 与 DeepSeek，先占用预算再转发一次请求。"""

import http.client
import json
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Literal
from urllib.parse import urlsplit

from backend.limits import ProbeError, Settings, StallError, price_for
from backend.profile import current
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.request import (
    TOOL_NAME,
    RequestTooLarge,
    request_byte_limit,
    validate_request,
)
from backend.providers.claude_agent.response import summarize
from backend.trace_log import trace

Forward = Callable[[bytes], tuple[int, bytes]]


@dataclass
class Guard:
    """每轮按入口限制实际HTTP尝试；跨轮累计限制由Budget独立管理。"""

    settings: Settings = field(repr=False)
    budget: Budget
    forward: Forward = field(repr=False)
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    attempts: int = 0
    observations: list[dict[str, object]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    failure_details: list[str] = field(default_factory=list)
    max_attempts: int = 4
    allowed_tools: frozenset[str] = frozenset({TOOL_NAME})
    temperature: Literal[0] | None = None
    run: str = ""  # 仅TRACE用的run标识
    upstream_status: int | None = None  # 最近一次非200的上游状态码(仅数字，不含正文)

    def accept(self, path: str, token: str, body: bytes) -> tuple[int, bytes]:
        if not secrets.compare_digest(token, "Bearer " + self.token):
            return self.reject("unauthorized")
        if urlsplit(path).path != "/v1/messages":
            return self.reject("unsupported_endpoint")
        trace(
            "model_req_received",
            self.run,
            attempt=self.attempts + 1,
            req_bytes=len(body),
            limit_bytes=request_byte_limit(self.settings.model),
        )
        started: float | None = None
        try:
            if not (
                self.settings.currency
                == self.budget.currency
                == price_for(self.settings.model).currency
            ):
                raise ProbeError("blocked", "模型计费币种与账本不一致")
            request = validate_request(
                body, self.settings.model, self.allowed_tools, temperature=self.temperature
            )
            retries = 0
            while True:  # 仅首字节停滞会重试；每次尝试各自预占并计入attempts
                if self.failures or self.attempts >= self.max_attempts:
                    raise ProbeError("blocked", "当前实验已停止或达到请求上限")
                request_id = self.budget.reserve(request.charge, datetime.now(UTC), self.run)
                self.attempts += 1
                trace(
                    "model_req_start",
                    self.run,
                    attempt=self.attempts,
                    req_bytes=len(request.body),
                    raw_bytes=len(body),
                    limit_bytes=request_byte_limit(self.settings.model),
                    stream=True,  # validate_request只接受stream=true
                    max_tokens=request.max_output,
                )
                started = time.monotonic()
                try:
                    status, content = self.forward(request.body)
                    break
                except StallError as stall:
                    if retries >= current().upstream_retries:
                        raise
                    retries += 1
                    # 停滞的那次预占不退款，保持已占用；SDK此时尚未收到任何字节。
                    self._trace_failure(stall.code, started, why=str(stall))
                    trace(
                        "upstream_retry",
                        self.run,
                        n=retries,
                        reason="first_byte_stall",
                        last_phase=stall.last_phase,
                        waited_s=stall.waited_s,
                    )
            if status != 200:
                self.upstream_status = status
                raise ProbeError("provider_error", f"上游 HTTP {status}")
            observation = summarize(content, request, self.settings.model, self.settings.currency)
            trace(
                "model_req_end",
                self.run,
                attempt=self.attempts,
                status=status,
                elapsed_ms=round((time.monotonic() - started) * 1000),
                resp_bytes=len(content),
                input_tokens=observation.get("input_tokens"),
                output_tokens=observation.get("output_tokens"),
                stop_reason=observation.get("stop_reason"),
                tools=observation.get("tool_names"),
            )
            self.budget.settle(request_id, Decimal(str(observation["usage_cost_upper"])))
            self.observations.append(observation)
            # 已发生的费用照实结算；违规工具响应不能交给 CLI 继续发请求。
            names = observation["tool_names"]
            if not isinstance(names, list) or any(name not in self.allowed_tools for name in names):
                raise ProbeError("blocked", "上游返回未授权工具，停止后续请求")
            return 200, content
        except RequestTooLarge as error:
            return self.reject_size(error)
        except ProbeError as error:
            self.failure_details.append(str(error))
            self._trace_failure(error.code, started, why=str(error))
            return self.reject(error.code)
        except (OSError, http.client.HTTPException) as error:
            self._trace_failure("unavailable", started, type(error).__name__)
            return self.reject("unavailable")

    def reject_size(
        self, error: RequestTooLarge, *, size_source: str = "serialized_bytes"
    ) -> tuple[int, bytes]:
        self.failure_details.append(str(error))
        trace(
            "model_req_rejected",
            self.run,
            attempt=self.attempts + 1,
            reason="request_too_large",
            req_bytes=error.size,
            limit_bytes=error.limit,
            phase=error.phase,
            size_source=size_source,
        )
        return self.reject(error.code)

    def _trace_failure(
        self, code: str, started: float | None, error_class: str = "", why: str = ""
    ) -> None:
        trace(
            "model_req_end",
            self.run,
            attempt=self.attempts,
            status="error",
            error=code,
            error_class=error_class,
            why=why,  # 我方静态原因文案，不含正文/URL
            elapsed_ms=None if started is None else round((time.monotonic() - started) * 1000),
        )

    def reject(self, code: str) -> tuple[int, bytes]:
        self.failures.append(code)
        # SDK 不应将错误正文或 key 带入日志；这里只发固定结构和安全错误码。
        return 400, json.dumps(
            {
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": code,
                },
            }
        ).encode("utf-8")


def handler_for(guard: Guard) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, format: str, *args: object) -> None:
            """本地请求包含令牌；不输出标准 HTTP 访问日志。"""

        def do_POST(self) -> None:
            self.connection.settimeout(current().upstream_timeout + 5)
            length: int | None = None
            limit = request_byte_limit(guard.settings.model)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or self.headers.get("Transfer-Encoding"):
                    raise ValueError
                if length > limit:
                    status, content = guard.reject_size(
                        RequestTooLarge(length, limit, "ingress"), size_source="content_length"
                    )
                else:
                    body = self.rfile.read(length)
                    if len(body) != length:
                        raise ValueError
                    status, content = guard.accept(
                        self.path, self.headers.get("Authorization", ""), body
                    )
            except (ValueError, OSError) as error:
                trace(
                    "model_req_rejected",
                    guard.run,
                    attempt=guard.attempts + 1,
                    reason="invalid_request",
                    declared_bytes=length,
                    limit_bytes=limit,
                    error_class=type(error).__name__,
                )
                status, content = guard.reject("invalid_request")
            self.send_response(status)
            self.send_header(
                "Content-Type", "text/event-stream" if status == 200 else "application/json"
            )
            self.send_header("Content-Length", str(len(content)))
            try:
                self.end_headers()
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                trace("client_disconnected", guard.run, attempt=guard.attempts)
                guard.failures.append("client_disconnected")

    return Handler


@contextmanager
def serve(guard: Guard) -> Iterator[str]:
    """单线程服务使检查和占用串行；监听端口由操作系统分配。"""
    server = HTTPServer(("127.0.0.1", 0), handler_for(guard))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=current().upstream_timeout + 5)

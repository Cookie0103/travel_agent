"""回环 HTTP 守卫连接 SDK 与 DeepSeek，先占用预算再转发一次请求。"""

import http.client
import json
import secrets
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Literal
from urllib.parse import urlsplit

from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.limits import ProbeError, Settings, price_for
from backend.providers.claude_agent.request import MAX_BYTES, TOOL_NAME, validate_request
from backend.providers.claude_agent.response import summarize

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

    def accept(self, path: str, token: str, body: bytes) -> tuple[int, bytes]:
        if not secrets.compare_digest(token, "Bearer " + self.token):
            return self.reject("unauthorized")
        if urlsplit(path).path != "/v1/messages":
            return self.reject("unsupported_endpoint")
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
            if self.failures or self.attempts >= self.max_attempts:
                raise ProbeError("blocked", "当前实验已停止或达到请求上限")
            request_id = self.budget.reserve(request.charge, datetime.now(UTC))
            self.attempts += 1
            status, content = self.forward(request.body)
            if status != 200:
                raise ProbeError("provider_error", f"上游 HTTP {status}")
            observation = summarize(content, request, self.settings.model, self.settings.currency)
            self.budget.settle(request_id, Decimal(str(observation["usage_cost_upper"])))
            self.observations.append(observation)
            # 已发生的费用照实结算；违规工具响应不能交给 CLI 继续发请求。
            names = observation["tool_names"]
            if not isinstance(names, list) or any(name not in self.allowed_tools for name in names):
                raise ProbeError("blocked", "上游返回未授权工具，停止后续请求")
            return 200, content
        except ProbeError as error:
            self.failure_details.append(str(error))
            return self.reject(error.code)
        except (OSError, http.client.HTTPException):
            return self.reject("unavailable")

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
            self.connection.settimeout(50)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BYTES or self.headers.get("Transfer-Encoding"):
                    raise ValueError
                body = self.rfile.read(length)
                status, content = guard.accept(
                    self.path, self.headers.get("Authorization", ""), body
                )
            except (ValueError, OSError):
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
        thread.join(timeout=55)

"""所有SDK的模型请求都经过这个本地代理：统一计量token/请求数，并按需注入API故障。

路径 /r/<run_id>/<上游路径> → https://api.deepseek.com/<上游路径>
OpenAI兼容端点用 /r/<id>，Anthropic兼容端点用 /r/<id>/anthropic。
响应整体缓冲后再转发（流式响应也一样），因此能从响应体里解析usage。
"""

import json
import os
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

UPSTREAM = "https://api.deepseek.com"
DUMP_DIR = Path(os.environ["BENCH_DUMP_DIR"]) if os.environ.get("BENCH_DUMP_DIR") else None


@dataclass
class RunTraffic:
    fail_status: int = 0  # 注入的错误状态码，0=不注入
    fail_count: int = 0  # 前N个模型请求返回错误
    requests: list[dict] = field(default_factory=list)

    @property
    def ok_requests(self) -> list[dict]:
        return [r for r in self.requests if r["status"] == 200]


def _usage(body: bytes) -> tuple[int, int]:
    """从JSON或SSE响应体里取 (输入token, 输出token)，兼容OpenAI与Anthropic两种格式。"""
    text = body.decode("utf-8", errors="replace")
    chunks = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")] or [text]
    tokens_in = tokens_out = 0
    for chunk in chunks:
        try:
            data = json.loads(chunk)
        except ValueError:
            continue
        for usage in (data.get("usage"), (data.get("message") or {}).get("usage")):
            if not usage:
                continue
            cached = (usage.get("cache_read_input_tokens") or 0) + (
                usage.get("cache_creation_input_tokens") or 0
            )
            tokens_in = max(
                tokens_in, usage.get("prompt_tokens") or (usage.get("input_tokens") or 0) + cached
            )
            tokens_out = max(
                tokens_out, usage.get("completion_tokens") or usage.get("output_tokens") or 0
            )
    return tokens_in, tokens_out


class Proxy:
    def __init__(self) -> None:
        self.runs: dict[str, RunTraffic] = {}
        self.client = httpx.Client(timeout=300)
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                proxy.handle(self)

            def log_message(self, *_args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def base(self, run_id: str) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/r/{run_id}"

    def register(self, run_id: str, traffic: RunTraffic) -> None:
        self.runs[run_id] = traffic

    def handle(self, h: BaseHTTPRequestHandler) -> None:
        _, _, run_id, rest = h.path.split("/", 3)
        traffic = self.runs[run_id]
        body = h.rfile.read(int(h.headers.get("Content-Length", 0)))
        record: dict = {"bytes_out": len(body)}
        traffic.requests.append(record)
        if DUMP_DIR:  # 调试用：保存框架实际发出的请求体（不含请求头，不含密钥）
            DUMP_DIR.mkdir(parents=True, exist_ok=True)
            (DUMP_DIR / f"{run_id}-{len(traffic.requests):02d}.json").write_bytes(body)
        if len(traffic.requests) <= traffic.fail_count:
            status, content = traffic.fail_status, b'{"error":{"message":"injected fault"}}'
            headers = {"content-type": "application/json", "retry-after": "1"}
        else:
            skip = {"host", "content-length", "accept-encoding", "connection"}
            upstream = self.client.post(
                f"{UPSTREAM}/{rest}",
                content=body,
                headers={k: v for k, v in h.headers.items() if k.lower() not in skip},
            )
            status, content = upstream.status_code, upstream.content
            headers = {"content-type": upstream.headers.get("content-type", "application/json")}
            record["tokens_in"], record["tokens_out"] = _usage(content)
        record["status"] = status
        h.send_response(status)
        for k, v in headers.items():
            h.send_header(k, v)
        h.send_header("Content-Length", str(len(content)))
        h.end_headers()
        h.wfile.write(content)

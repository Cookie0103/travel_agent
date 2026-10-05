"""固定供应商Messages传输；复用进程总期限覆盖DNS、连接和慢流。"""

import http.client
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from backend.providers.claude_agent.limits import ProbeError, Provider
from backend.providers.claude_agent.process import run_process
from backend.providers.claude_agent.profile import current
from backend.providers.claude_agent.response import message_stopped
from backend.trace_log import FILE_ENV, RUN_ENV, trace

MAX_RESPONSE_BYTES = 1_048_576


# live.py 在独占锁内（同一时刻仅一个live run）设置；保持forward_messages签名不变以兼容替身。
child_trace: tuple[Path, str] | None = None


def forward_messages(provider: Provider, api_key: str, body: bytes) -> tuple[int, bytes]:
    """整个 DNS/连接/读取在可回收进程中限时，真实 key 仅通过 stdin 传递。"""
    root = Path(__file__).resolve().parents[3]
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "TEMP",
            "TMP",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "TRAVEL_PROFILE",
        }
    }
    env.update(PYTHONPATH=str(root), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    target = child_trace
    run = target[1] if target else ""
    if target:  # 转发子进程的TRACE写入文件，由父进程Tail转印
        env.update({FILE_ENV: str(target[0]), RUN_ENV: run})
    started = time.monotonic()
    try:
        result = run_process(
            [sys.executable, "-m", "backend.providers.claude_agent.http"],
            root,
            env,
            current().upstream_timeout,
            json.dumps({"provider": provider, "key": api_key, "body": body.decode("utf-8")}),
        )
    except subprocess.TimeoutExpired:
        trace(
            "timeout_fired",
            run,
            layer="upstream_process",
            limit_s=current().upstream_timeout,
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )
        raise ProbeError("timeout", "上游请求总期限已到，保留预占") from None
    if result.returncode != 0:
        trace("model_req_child_failed", run, exit_code=result.returncode)
        raise ProbeError("unavailable", "上游请求工作进程失败")
    try:
        raw = json.loads(result.stdout)
        if raw.get("status") == "error" and raw.get("code") == "timeout":
            trace(
                "timeout_fired",
                run,
                layer="upstream_socket",
                limit_s=current().upstream_timeout - 5,
                elapsed_ms=round((time.monotonic() - started) * 1000),
            )
            raise ProbeError("timeout", "上游请求超时，保留预占")
        if raw.get("status") != "ok" or type(raw.get("http_status")) is not int:
            raise ValueError
        content = raw["content"]
        if not isinstance(content, str):
            raise ValueError
        return raw["http_status"], content.encode("utf-8")
    except (ValueError, AttributeError, KeyError, TypeError):
        raise ProbeError("unavailable", "上游请求失败或返回格式无效") from None


def _direct_request(
    api_key: str, body: bytes, provider: Provider = "deepseek"
) -> tuple[int, bytes]:
    """不使用代理环境、不跟随重定向；一次 reserve 对应一次 HTTP 尝试。"""
    if provider not in {"deepseek", "anthropic"}:
        raise ProbeError("blocked", "未知供应商；禁止自定义转发地址")
    host, path, authorization = (
        ("api.deepseek.com", "/anthropic/v1/messages", "Authorization")
        if provider == "deepseek"
        else ("api.anthropic.com", "/v1/messages", "x-api-key")
    )
    connection = http.client.HTTPSConnection(host, timeout=current().upstream_timeout - 5)
    started, phase = time.monotonic(), "send"  # 仅用于TRACE：失败发生在哪个阶段

    def since() -> int:
        return round((time.monotonic() - started) * 1000)

    try:
        connection.request(
            "POST",
            path,
            body,
            {
                authorization: f"Bearer {api_key}" if provider == "deepseek" else api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
        )
        phase = "headers"
        trace("model_req_sent", ms=since())
        response = connection.getresponse()
        phase = "body"
        trace("model_req_first_byte", ms=since(), http_status=response.status)
        content = (
            _read_sse(response, started)
            if response.status == 200
            else response.read(MAX_RESPONSE_BYTES + 1)
        )
        if len(content) > MAX_RESPONSE_BYTES:
            raise ProbeError("provider_error", "上游响应超过实验上限")
        trace("model_req_body_done", ms=since(), resp_bytes=len(content))
        return response.status, content
    except BaseException as error:
        trace("model_req_child_error", phase=phase, error_class=type(error).__name__, ms=since())
        raise
    finally:
        connection.close()


def _read_sse(response: http.client.HTTPResponse, started: float | None = None) -> bytes:
    """message_stop已到即可关连接，避免完整响应继续等HTTP EOF。"""
    content = bytearray()
    pending = b""
    while True:
        chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - len(content)))
        if not chunk:
            return bytes(content)
        if started is not None and not content:
            trace("model_req_first_chunk", ms=round((time.monotonic() - started) * 1000))
        content.extend(chunk)
        if len(content) > MAX_RESPONSE_BYTES:
            raise ProbeError("provider_error", "上游响应超过实验上限")
        pending = (pending + chunk).replace(b"\r\n", b"\n")
        while b"\n\n" in pending:
            frame, _, pending = pending.partition(b"\n\n")
            if message_stopped(frame):
                return bytes(content)


def main() -> None:
    """私有传输进程：错误只回固定分类，不打印密钥或 HTTP 异常正文。"""
    try:
        request = json.loads(sys.stdin.read())
        status, content = _direct_request(
            request["key"], request["body"].encode("utf-8"), request.get("provider", "deepseek")
        )
        response: dict[str, object] = {
            "status": "ok",
            "http_status": status,
            "content": content.decode("utf-8"),
        }
    except TimeoutError:
        response = {"status": "error", "code": "timeout"}
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException, ProbeError):
        response = {"status": "error"}
    print(json.dumps(response))


if __name__ == "__main__":
    main()

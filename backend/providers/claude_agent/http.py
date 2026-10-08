"""固定供应商Messages传输；复用进程总期限覆盖DNS、连接和慢流。"""

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from backend.limits import ProbeError, Provider, StallError
from backend.profile import current
from backend.providers.claude_agent.process import progress_hook, run_process, spawn_hook
from backend.providers.claude_agent.response import message_stopped
from backend.trace_log import FILE_ENV, RUN_ENV, trace

MAX_RESPONSE_BYTES = 1_048_576


# live.py 在独占锁内（同一时刻仅一个live run）设置；保持forward_messages签名不变以兼容替身。
child_trace: tuple[Path, str] | None = None
SPAWN_TS_ENV = "TRAVEL_CHILD_SPAWN_TS"  # 父进程spawn时刻(epoch)，子进程据此报告启动耗时
# 子进程写入trace文件的阶段事件；首字节(响应头)之后的事件意味着已有响应字节。
_CHILD_PHASES = (
    "child_start",
    "child_stdin_read",
    "child_connecting",
    "child_dns_done",
    "child_connected",
    "model_req_sent",
    "model_req_first_byte",
    "model_req_first_chunk",
    "model_req_body_done",
    "model_req_child_error",
)
_RECEIVED = {"model_req_first_byte", "model_req_first_chunk", "model_req_body_done"}


def _now() -> float:
    return time.monotonic()


class _Watch:
    """父进程侧：等待期间读取子进程trace文件，记录最后阶段，并在无响应头时触发首字节看门狗。"""

    def __init__(self, path: Path, run: str, first_byte_timeout: float) -> None:
        self.path, self.run, self.limit = path, run, first_byte_timeout
        try:
            self.offset = path.stat().st_size  # 只看本次spawn之后写入的行
        except OSError:
            self.offset = 0
        self.phase, self.received, self.started = "none", False, _now()

    def spawned(self, pid: int) -> None:
        self.started = _now()
        trace("child_spawned", self.run, pid=pid)

    def drain(self) -> None:
        try:
            with self.path.open("rb") as stream:
                stream.seek(self.offset)
                data = stream.read()
        except OSError:
            return
        complete = data[: data.rfind(b"\n") + 1]
        self.offset += len(complete)
        for line in complete.decode("utf-8", "replace").splitlines():
            try:
                event = json.loads(line.removeprefix("TRACE "))
            except ValueError:
                continue  # 与worker并发追加时可能截到半行
            name = event.get("ev") if isinstance(event, dict) else None
            if name in _CHILD_PHASES:
                self.phase = str(name)
                self.received = self.received or name in _RECEIVED

    def waited(self) -> float:
        return round(_now() - self.started, 1)

    def __call__(self) -> None:
        self.drain()
        if self.limit > 0 and not self.received and _now() - self.started > self.limit:
            raise StallError(self.phase, self.waited())


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
    limits = current()
    target = child_trace
    scratch: Path | None = None
    if target is None and limits.first_byte_timeout > 0:  # 看门狗必须能读到子进程阶段
        handle, name = tempfile.mkstemp(prefix="upstream-trace-", suffix=".jsonl")
        os.close(handle)
        scratch = Path(name)
        target = (scratch, "")
    run = target[1] if target else ""
    if target:  # 转发子进程的TRACE写入文件，由父进程Tail转印
        env.update({FILE_ENV: str(target[0]), RUN_ENV: run})
    env[SPAWN_TS_ENV] = repr(time.time())
    watch = _Watch(target[0], run, limits.first_byte_timeout) if target else None
    tokens = (
        (progress_hook.set(watch), spawn_hook.set(watch.spawned)) if watch is not None else None
    )
    started = time.monotonic()
    try:
        result = run_process(
            [sys.executable, "-m", "backend.providers.claude_agent.http"],
            root,
            env,
            limits.upstream_timeout,
            json.dumps({"provider": provider, "key": api_key, "body": body.decode("utf-8")}),
        )
    except StallError:
        assert watch is not None
        watch.drain()  # 子进程已被回收；读取终止前最后写出的阶段
        if watch.received:  # 看门狗与首字节竞态：已有响应头则不可重试
            trace("child_last_phase", run, phase=watch.phase)
            raise ProbeError("timeout", "上游请求总期限已到，保留预占") from None
        trace("child_last_phase", run, phase=watch.phase)
        trace(
            "timeout_fired",
            run,
            layer="upstream_first_byte",
            limit_s=limits.first_byte_timeout,
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )
        raise StallError(watch.phase, watch.waited()) from None
    except subprocess.TimeoutExpired:
        if watch is not None:
            watch.drain()
            trace("child_last_phase", run, phase=watch.phase)
        trace(
            "timeout_fired",
            run,
            layer="upstream_process",
            limit_s=limits.upstream_timeout,
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )
        raise ProbeError("timeout", "上游请求总期限已到，保留预占") from None
    finally:
        if tokens is not None:
            progress_hook.reset(tokens[0])
            spawn_hook.reset(tokens[1])
        if scratch is not None:
            scratch.unlink(missing_ok=True)
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
    started, phase = time.monotonic(), "connect"  # 仅用于TRACE：失败发生在哪个阶段

    def since() -> int:
        return round((time.monotonic() - started) * 1000)

    try:
        trace("child_connecting", host=host)
        if callable(getattr(connection, "connect", None)):
            # 显式分步：DNS(独立解析一次，系统缓存命中) → TCP+TLS握手；各自留痕以定位停滞处
            socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            trace("child_dns_done", ms=since())
            connection.connect()
            trace("child_connected", ms=since())  # TCP+TLS均已完成
        phase = "send"
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
        raw_input = sys.stdin.read()
        trace("child_stdin_read", bytes=len(raw_input))
        request = json.loads(raw_input)
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
    boot_ms: int | None
    try:  # 导入均为标准库/轻量模块；boot_ms=从父进程spawn到此处(含bootstrap与导入)
        boot_ms = round((time.time() - float(os.environ.get(SPAWN_TS_ENV, "nan"))) * 1000)
    except (ValueError, OverflowError):
        boot_ms = None
    trace("child_start", pid=os.getpid(), boot_ms=boot_ms)
    main()

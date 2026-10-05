"""给 SDK 工作进程设置期限；最后保护同时回收其 CLI 子进程。"""

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from threading import Event, Thread

from backend.providers.claude_agent.limits import ProbeError
from backend.providers.claude_agent.profile import current
from backend.providers.claude_agent.windows_job import WindowsJob
from backend.trace_log import trace

# 调用方线程内的环境进度钩子：不改run_process调用形状（含测试替身），显式progress优先。
progress_hook: ContextVar[Callable[[], None] | None] = ContextVar("progress_hook", default=None)
spawn_hook: ContextVar[Callable[[int], None] | None] = ContextVar("spawn_hook", default=None)


def run_process(
    args: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    input_text: str = "",
    *,
    cancelled: Event | None = None,
    progress: Callable[[], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """先由 worker 自行取消；父期限到达才对自己创建的进程树强制终止。"""
    progress = progress or progress_hook.get()
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    job = WindowsJob() if sys.platform == "win32" else None
    # Windows venv python.exe 会立刻启动真正解释器；用基础解释器启动无 SDK 的握手器。
    interpreter = str(Path(sys.base_prefix) / "python.exe") if os.name == "nt" else sys.executable
    command = [interpreter, str(Path(__file__).with_name("bootstrap.py")), *args]
    with subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        encoding="utf-8",
        creationflags=flags,
        start_new_session=os.name != "nt",
    ) as process:
        try:
            on_spawn = spawn_hook.get()
            if on_spawn is not None:
                on_spawn(process.pid)
            if job is not None:
                job.assign(process.pid)
            # 根因：Python 3.12 的 communicate(input=…, timeout=…) 在首次超时后以 input=None
            # 续调时不再继续写 stdin，>64KiB(管道容量)的载荷会永远卡在管道里。
            # 因此 stdin 由独立线程写完并关闭，communicate 只负责读 stdout/stderr。
            feeder = _feed(process, "start\n" + input_text)
            try:
                stdout, stderr = communicate(process, "", timeout, cancelled, progress)
            finally:
                feeder.join(timeout=1)
        except subprocess.TimeoutExpired:
            if job is not None:
                job.close()
                process.communicate(timeout=10)
            else:
                terminate_tree(process)
            raise
        except BaseException:
            # 取消/事件写入失败也必须清理自己启动的整个进程树。
            if job is not None:
                job.close()
                process.communicate(timeout=10)
            else:
                terminate_tree(process)
            raise
        finally:
            if job is not None:
                job.close()
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def _feed(process: subprocess.Popen[str], payload: str) -> Thread:
    stream = process.stdin
    assert stream is not None
    process.stdin = None  # 使communicate不接管(也不提前关闭)stdin

    def write() -> None:
        try:
            stream.write(payload)
            stream.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass  # 子进程已退出/被终止：由退出码和期限分类
        finally:
            try:
                stream.close()
            except (BrokenPipeError, OSError, ValueError):
                pass

    thread = Thread(target=write, daemon=True)
    thread.start()
    return thread


def communicate(
    process: subprocess.Popen[str],
    payload: str,
    timeout: float,
    cancelled: Event | None,
    progress: Callable[[], None] | None,
) -> tuple[str, str]:
    deadline = time.monotonic() + timeout
    pending: str | None = payload
    while True:
        if cancelled is not None and cancelled.is_set():
            raise ProbeError("cancelled", "执行已取消")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            result = process.communicate(input=pending, timeout=min(0.2, remaining))
        except subprocess.TimeoutExpired:
            pending = None
            if progress is not None:
                progress()
        else:
            if progress is not None:
                progress()
            return result


def terminate_tree(process: subprocess.Popen[str]) -> None:
    """PID 来自本次 Popen，不枚举或终止用户的其他 Claude 会话。"""
    if sys.platform != "win32":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    if process.poll() is None:
        process.kill()
    process.communicate(timeout=10)


def invoke_worker(
    cli: Path,
    directory: Path,
    env: dict[str, str],
    *,
    module: str,
    payload: dict[str, object] | None = None,
    cancelled: Event | None = None,
    progress: Callable[[], None] | None = None,
) -> dict[str, object]:
    """探针和正式 CLI 共用退出码、期限与 JSON 边界；不回传原始 stderr。"""
    started = time.monotonic()
    try:
        result = run_process(
            [sys.executable, "-m", module, str(cli)],
            cwd=directory,
            env=env,
            timeout=current().process_timeout,
            input_text=json.dumps(payload) if payload is not None else "",
            cancelled=cancelled,
            progress=progress,
        )
    except subprocess.TimeoutExpired:
        trace(
            "timeout_fired",
            layer="process",
            limit_s=current().process_timeout,
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )
        return {"status": "error", "code": "timeout"}
    except ProbeError as error:
        return {"status": "error", "code": error.code}
    if result.returncode != 0:
        return {"status": "error", "code": "worker_exit", "exit_code": result.returncode}
    try:
        raw: object = json.loads(result.stdout.strip())
    except ValueError:
        raise ProbeError("provider_error", "SDK 工作进程没有返回结构化摘要") from None
    if not isinstance(raw, dict) or raw.get("status") not in {"success", "error"}:
        raise ProbeError("provider_error", "SDK 工作进程摘要不符合契约")
    return {str(key): value for key, value in raw.items()}

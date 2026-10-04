"""给 SDK 工作进程设置期限；最后保护同时回收其 CLI 子进程。"""

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event

from backend.providers.claude_agent.limits import ProbeError
from backend.providers.claude_agent.windows_job import WindowsJob


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
            if job is not None:
                job.assign(process.pid)
            stdout, stderr = communicate(
                process, "start\n" + input_text, timeout, cancelled, progress
            )
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
    try:
        result = run_process(
            [sys.executable, "-m", module, str(cli)],
            cwd=directory,
            env=env,
            timeout=120,
            input_text=json.dumps(payload) if payload is not None else "",
            cancelled=cancelled,
            progress=progress,
        )
    except subprocess.TimeoutExpired:
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

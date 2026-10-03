"""给 SDK 工作进程设置期限；最后保护同时回收其 CLI 子进程。"""

import os
import signal
import subprocess
import sys
from pathlib import Path

from backend.providers.sdk_probe.windows_job import WindowsJob


def run_process(
    args: list[str], cwd: Path, env: dict[str, str], timeout: float, input_text: str = ""
) -> subprocess.CompletedProcess[str]:
    """先由 worker 自行取消；父期限到达才对自己创建的进程树强制终止。"""
    flags = (
        subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    )
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
            stdout, stderr = process.communicate(input="start\n" + input_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            if job is not None:
                job.close()
                process.communicate(timeout=10)
            else:
                terminate_tree(process)
            raise
        except OSError:
            process.kill()
            raise
        finally:
            if job is not None:
                job.close()
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


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

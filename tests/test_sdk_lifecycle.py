"""真实慢流和受控挂起进程验证期限，避免只测模拟 timeout 异常。"""

import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from backend.limits import ProbeError
from backend.providers.claude_agent.process import invoke_worker, run_process
from backend.providers.claude_agent.windows_job import WindowsJob


def test_continuous_slow_stream_cannot_extend_total_deadline(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(2)

        def slow_peer() -> None:
            with listener.accept()[0] as peer:
                peer.recv(8192)
                peer.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
                for _ in range(1000):
                    try:
                        peer.sendall(b"a")
                    except OSError:
                        return
                    time.sleep(0.01)

        thread = threading.Thread(target=slow_peer, daemon=True)
        thread.start()
        port = listener.getsockname()[1]
        client = (
            "import http.client; "
            f"c=http.client.HTTPConnection('127.0.0.1',{port},timeout=2); "
            "c.request('GET','/'); c.getresponse().read()"
        )
        started = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            run_process([sys.executable, "-c", client], tmp_path, dict(os.environ), timeout=1)
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert time.monotonic() - started < 3


def test_timeout_terminates_spawned_child_as_well_as_worker(tmp_path: Path) -> None:
    heartbeat = tmp_path / "heartbeat"
    child = (
        "import time; from pathlib import Path; p=Path('heartbeat'); "
        "\nwhile True:\n p.write_text(str(time.time_ns()),encoding='utf-8'); time.sleep(0.01)"
    )
    parent = (
        "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
        + repr(child)
        + "]); time.sleep(60)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, "-c", parent], tmp_path, dict(os.environ), timeout=1)
    assert heartbeat.exists()
    previous = heartbeat.read_text(encoding="utf-8")
    time.sleep(0.15)
    assert heartbeat.read_text(encoding="utf-8") == previous


def test_worker_nonzero_exit_overrides_success_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def failed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["worker"], 1, '{"status":"success"}', "private")

    monkeypatch.setattr("backend.providers.claude_agent.process.run_process", failed)
    assert invoke_worker(tmp_path / "cli", tmp_path, {}, module="worker") == {
        "status": "error",
        "code": "worker_exit",
        "exit_code": 1,
    }


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job 分配语义")
def test_worker_cannot_spawn_children_before_job_assignment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = tmp_path / "started"
    assign = WindowsJob.assign

    def delayed_assign(self: WindowsJob, pid: int) -> None:
        time.sleep(0.25)
        assert not marker.exists()
        assign(self, pid)

    monkeypatch.setattr(WindowsJob, "assign", delayed_assign)
    script = "from pathlib import Path; Path('started').write_text('yes',encoding='utf-8')"
    result = run_process([sys.executable, "-c", script], tmp_path, dict(os.environ), timeout=2)
    assert result.returncode == 0 and marker.exists()


def test_bootstrap_preserves_stdin_payload_for_child(tmp_path: Path) -> None:
    result = run_process(
        [sys.executable, "-c", "import sys; print(sys.stdin.read())"],
        tmp_path,
        dict(os.environ),
        timeout=2,
        input_text="private-payload",
    )
    assert result.returncode == 0 and result.stdout.strip() == "private-payload"


def test_cancel_stops_running_child_after_publishing_progress(tmp_path: Path) -> None:
    cancelled = threading.Event()
    marker = tmp_path / "running"
    script = (
        "from pathlib import Path; import time; "
        "Path('running').write_text('started',encoding='utf-8'); time.sleep(60)"
    )

    def progress() -> None:
        if marker.exists():
            cancelled.set()

    started = time.monotonic()
    with pytest.raises(ProbeError, match="cancelled"):
        run_process(
            [sys.executable, "-c", script],
            tmp_path,
            dict(os.environ),
            timeout=5,
            cancelled=cancelled,
            progress=progress,
        )
    assert marker.exists() and time.monotonic() - started < 3


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_unsupported_platform_never_loads_windows_api(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("非Windows平台不应加载kernel32")

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(ctypes, "WinDLL", forbidden, raising=False)
    with pytest.raises(OSError, match="Windows"):
        WindowsJob()

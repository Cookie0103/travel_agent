"""上游首字节停滞：阶段TRACE、看门狗、有界重试；DEFAULT行为不变。全部离线（替身进程/连接）。"""

import io
import json
import socket
import subprocess
import sys
from decimal import Decimal
from http.client import HTTPSConnection
from pathlib import Path

import pytest

from backend import trace_log
from backend.limits import Settings
from backend.profile import DEFAULT, HUMAN, RELAXED
from backend.providers.claude_agent import http, process
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import worker_environment
from backend.providers.claude_agent.guard import Guard
from backend.trace_log import FILE_ENV
from tests.test_sdk_guard import request_body, response_body

Step = tuple[str, object]  # ("ev", 事件名) | ("tick", 秒) | ("done", http_status) | ("timeout", 0)
OK = ("done", 200)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Harness:
    """替身run_process：按脚本写子进程阶段、推进假时钟、调用环境进度钩子（与真实run_process一致）。"""

    def __init__(self, scripts: list[list[Step]], clock: Clock) -> None:
        self.scripts, self.clock, self.spawns = scripts, clock, 0

    def __call__(
        self, args: list[str], cwd: Path, env: dict[str, str], timeout: float, input_text: str
    ) -> subprocess.CompletedProcess[str]:
        script = self.scripts[self.spawns]
        self.spawns += 1
        spawn, progress = process.spawn_hook.get(), process.progress_hook.get()
        assert spawn is not None and progress is not None
        spawn(4242)
        for kind, value in script:
            if kind == "ev":
                with open(env[FILE_ENV], "a", encoding="utf-8") as stream:
                    stream.write("TRACE " + json.dumps({"ev": value}) + "\n")
            elif kind == "tick":
                assert isinstance(value, float)
                self.clock.now += value
                progress()  # 看门狗触发时在此抛出（真实run_process会先回收进程树）
            elif kind == "timeout":
                raise subprocess.TimeoutExpired(args, timeout)
            else:
                assert isinstance(value, int)
                payload = {
                    "status": "ok",
                    "http_status": value,
                    "content": response_body().decode() if value == 200 else "x",
                }
                return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        raise AssertionError("script must end with done/timeout/stall")


def stall_script() -> list[Step]:
    return [("ev", "child_start"), ("ev", "child_connecting"), ("tick", 10.0), ("tick", 16.0)]


def success_script() -> list[Step]:
    return [("ev", "child_start"), ("ev", "model_req_first_byte"), ("tick", 1.0), OK]


class Rig:
    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        profile: str,
        scripts: list[list[Step]],
    ) -> None:
        monkeypatch.setenv("TRAVEL_PROFILE", profile)
        monkeypatch.setattr(trace_log, "_stdout", True)
        self.clock = Clock()
        self.harness = Harness(scripts, self.clock)
        monkeypatch.setattr(http, "_now", self.clock)
        monkeypatch.setattr(http, "run_process", self.harness)
        monkeypatch.setattr(http, "child_trace", (tmp_path / "child.jsonl", "abcdef01"))
        self.budget = Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(5))
        self.guard = Guard(
            Settings("private-key", "deepseek-flash", Decimal(5), Decimal(0)),
            self.budget,
            lambda body: http.forward_messages("deepseek", "private-key", body),
            run="abcdef01",
        )

    def post(self) -> tuple[int, bytes]:
        return self.guard.accept("/v1/messages", "Bearer " + self.guard.token, request_body())


def events(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    lines = [x for x in capsys.readouterr().out.splitlines() if x.startswith("TRACE ")]
    return [json.loads(x.removeprefix("TRACE ")) for x in lines]


def named(records: list[dict[str, object]], name: str) -> list[dict[str, object]]:
    return [r for r in records if r["ev"] == name]


def test_stalled_first_try_is_killed_and_retried_invisibly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = Rig(tmp_path, monkeypatch, "human", [stall_script(), success_script()])
    status, content = rig.post()
    records = events(capsys)
    assert status == 200 and b"message_stop" in content and rig.guard.failures == []
    assert rig.guard.attempts == 2 and rig.harness.spawns == 2
    assert rig.budget.totals()[0] == 2  # 停滞那次预占不退，重试另占一次
    (retry,) = named(records, "upstream_retry")
    assert retry["n"] == 1 and retry["reason"] == "first_byte_stall"
    assert retry["last_phase"] == "child_connecting" and retry["waited_s"] == 26.0
    assert [r["attempt"] for r in named(records, "model_req_start")] == [1, 2]
    assert len(named(records, "child_spawned")) == 2
    assert named(records, "child_last_phase")[0]["phase"] == "child_connecting"
    assert named(records, "timeout_fired")[0]["layer"] == "upstream_first_byte"
    assert "private-key" not in json.dumps(records)


def test_all_tries_stall_then_fail_like_today(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = Rig(tmp_path, monkeypatch, "human", [stall_script() for _ in range(3)])
    status, content = rig.post()
    records = events(capsys)
    assert status == 400 and b"timeout" in content and b"private-key" not in content
    assert rig.guard.failures == ["timeout"] and rig.guard.attempts == 3
    assert rig.harness.spawns == 3 and len(named(records, "upstream_retry")) == 2
    assert rig.budget.totals()[0] == 3
    assert named(records, "model_req_end")[-1]["error"] == "timeout"
    assert rig.post()[0] == 400 and rig.harness.spawns == 3  # 实验已停止，不再转发


def test_stall_after_first_byte_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script: list[Step] = [("ev", "model_req_first_byte"), ("tick", 24.0), ("tick", 90.0)]
    rig = Rig(tmp_path, monkeypatch, "human", [[*script, ("timeout", 0)], success_script()])
    status, _ = rig.post()
    records = events(capsys)
    assert status == 400 and rig.guard.failures == ["timeout"]
    assert rig.guard.attempts == 1 and rig.harness.spawns == 1
    assert not named(records, "upstream_retry")
    assert named(records, "timeout_fired")[0]["layer"] == "upstream_process"
    assert named(records, "child_last_phase")[0]["phase"] == "model_req_first_byte"


@pytest.mark.parametrize("http_status", [400, 429, 503])
def test_http_error_status_is_not_retried(
    http_status: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script: list[Step] = [("ev", "model_req_first_byte"), ("done", http_status)]
    rig = Rig(tmp_path, monkeypatch, "human", [script, success_script()])
    status, _ = rig.post()
    assert status == 400 and rig.guard.failures == ["provider_error"]
    assert rig.guard.attempts == 1 and rig.harness.spawns == 1
    assert not named(events(capsys), "upstream_retry")


@pytest.mark.parametrize("profile,expected", [("default", DEFAULT), ("relaxed", RELAXED)])
def test_default_and_relaxed_have_no_watchdog_or_retries(
    profile: str,
    expected: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (expected.first_byte_timeout, expected.upstream_retries) == (0.0, 0)  # type: ignore[attr-defined]
    # 远超HUMAN首字节期限仍不被看门狗杀掉；也不重试
    script: list[Step] = [("ev", "child_connecting"), ("tick", 100.0), OK]
    rig = Rig(tmp_path, monkeypatch, profile, [script, success_script()])
    assert rig.post()[0] == 200 and rig.harness.spawns == 1
    assert not named(events(capsys), "upstream_retry")
    rig2 = Rig(tmp_path / "b", monkeypatch, profile, [[("tick", 500.0), ("timeout", 0)]])
    (tmp_path / "b").mkdir(exist_ok=True)
    assert rig2.post()[0] == 400 and rig2.guard.attempts == 1 and rig2.harness.spawns == 1


def test_default_without_trace_file_passes_no_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRAVEL_PROFILE", raising=False)
    monkeypatch.setattr(http, "child_trace", None)
    seen: list[object] = []

    def fake(
        args: list[str], cwd: Path, env: dict[str, str], timeout: float, input_text: str
    ) -> subprocess.CompletedProcess[str]:
        seen.extend([process.progress_hook.get(), process.spawn_hook.get(), FILE_ENV in env])
        payload = {"status": "ok", "http_status": 200, "content": "x"}
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    monkeypatch.setattr(http, "run_process", fake)
    assert http.forward_messages("deepseek", "k", b"{}") == (200, b"x")
    assert seen == [None, None, False]


def test_human_without_trace_file_uses_private_scratch_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRAVEL_PROFILE", "human")
    monkeypatch.setattr(http, "child_trace", None)
    paths: list[Path] = []

    def fake(
        args: list[str], cwd: Path, env: dict[str, str], timeout: float, input_text: str
    ) -> subprocess.CompletedProcess[str]:
        paths.append(Path(env[FILE_ENV]))
        assert paths[0].exists() and process.progress_hook.get() is not None
        payload = {"status": "ok", "http_status": 200, "content": "x"}
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    monkeypatch.setattr(http, "run_process", fake)
    assert http.forward_messages("deepseek", "k", b"{}")[0] == 200
    assert not paths[0].exists() and process.progress_hook.get() is None


class FakeSocket:
    def close(self) -> None:
        pass


class FakeResponse:
    status = 200

    def __init__(self) -> None:
        self.chunks = [response_body()]

    def read1(self, size: int) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""


def test_child_phase_events_are_emitted_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    trace_file = tmp_path / "trace.jsonl"
    monkeypatch.setenv(FILE_ENV, str(trace_file))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"key": "k", "body": "{}"})))
    conn = HTTPSConnection

    def connect(self: HTTPSConnection) -> None:
        self.sock = FakeSocket()

    def getresponse(self: HTTPSConnection) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr(conn, "connect", connect)
    monkeypatch.setattr(conn, "request", lambda *a, **k: None)
    monkeypatch.setattr(conn, "getresponse", getresponse)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    http.main()
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    order = [
        json.loads(x.removeprefix("TRACE "))["ev"] for x in trace_file.read_text().splitlines()
    ]
    assert order == [
        "child_stdin_read",
        "child_connecting",
        "child_dns_done",
        "child_connected",
        "model_req_sent",
        "model_req_first_byte",
        "model_req_first_chunk",
        "model_req_body_done",
    ]
    assert set(order[1:]) <= set(http._CHILD_PHASES)


def test_child_start_is_first_event_of_real_subprocess(tmp_path: Path) -> None:
    trace_file = tmp_path / "trace.jsonl"
    root = Path(http.__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "-m", "backend.providers.claude_agent.http"],
        cwd=root,
        input="",  # 空stdin：不联网，走固定错误分类
        env={"PYTHONPATH": str(root), FILE_ENV: str(trace_file), http.SPAWN_TS_ENV: "1.0"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert json.loads(result.stdout) == {"status": "error"}
    records = [json.loads(x.removeprefix("TRACE ")) for x in trace_file.read_text().splitlines()]
    assert [r["ev"] for r in records] == ["child_start", "child_stdin_read"]
    assert isinstance(records[0]["pid"], int) and isinstance(records[0]["boot_ms"], int)


def test_human_limits_order_and_retry_worst_case_fit_api_timeout(tmp_path: Path) -> None:
    assert (HUMAN.first_byte_timeout, HUMAN.upstream_retries) == (25.0, 2)
    assert HUMAN.request_worst_case == 120 + 2 * 25 == 170
    env = worker_environment(
        {"TRAVEL_PROFILE": "human"}, tmp_path, Path.cwd(), "http://x", "t", "m"
    )
    api = int(env["API_TIMEOUT_MS"]) / 1000
    assert HUMAN.first_byte_timeout < HUMAN.upstream_timeout < api < HUMAN.worker_timeout
    assert api > HUMAN.request_worst_case  # 否则Claude CLI先于守卫放弃
    assert (
        api > (HUMAN.upstream_retries + 1) * HUMAN.first_byte_timeout + HUMAN.upstream_timeout - 25
    )
    assert HUMAN.worker_timeout < HUMAN.process_timeout < HUMAN.run_timeout
    default = worker_environment({}, tmp_path, Path.cwd(), "http://x", "t", "m")
    relaxed = worker_environment({"TRAVEL_PROFILE": "relaxed"}, tmp_path, Path.cwd(), "x", "t", "m")
    assert default["API_TIMEOUT_MS"] == "100000" and relaxed["API_TIMEOUT_MS"] == "130000"

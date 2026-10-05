"""传输期限失败仍保留预占，工作进程只继承期限档位而不继承凭据。"""

import io
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from backend.providers.claude_agent import http
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.guard import Guard
from backend.providers.claude_agent.limits import ProbeError, Settings
from tests.test_sdk_guard import request_body


@pytest.mark.parametrize("profile,deadline", [("default", 90), ("relaxed", 120)])
@pytest.mark.parametrize("timeout_kind", ["process", "socket"])
def test_transport_deadline_stops_once_without_leaking_credentials(
    profile: str, deadline: int, timeout_kind: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    attempts = 0
    monkeypatch.setenv("TRAVEL_PROFILE", profile)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "parent-private-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "other-private-key")

    def stalled(
        args: list[str], cwd: Path, env: dict[str, str], timeout: float, input_text: str
    ) -> subprocess.CompletedProcess[str]:
        nonlocal attempts
        attempts += 1
        assert timeout == deadline and env["TRAVEL_PROFILE"] == profile
        assert not {"DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"}.intersection(env)
        assert "parent-private-key" not in str(args) + str(env)
        assert json.loads(input_text)["key"] == "parent-private-key"
        if timeout_kind == "process":
            raise subprocess.TimeoutExpired(args, timeout)
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"status": "error", "code": "timeout"}), ""
        )

    monkeypatch.setattr(http, "run_process", stalled)
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(5))
    guard = Guard(
        Settings("parent-private-key", "deepseek-flash", Decimal(5), Decimal(0)),
        budget,
        lambda body: http.forward_messages("deepseek", "parent-private-key", body),
    )
    for _ in range(2):
        status, content = guard.accept("/v1/messages", "Bearer " + guard.token, request_body())
        assert status == 400
        assert b"private-key" not in content
    assert attempts == 1 and budget.totals()[0] == 1
    assert budget.totals()[1] > 0
    assert [entry.kind for entry in budget.entries()] == ["attempt"]
    assert guard.failures[0] == "timeout"


def test_socket_timeout_preserves_only_fixed_classification(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"key": "private-key", "body": "private-prompt"}))
    )

    def stalled(*args: object, **kwargs: object) -> tuple[int, bytes]:
        raise TimeoutError("private-key/private-prompt")

    monkeypatch.setattr(http, "_direct_request", stalled)
    http.main()
    assert json.loads(capsys.readouterr().out) == {"status": "error", "code": "timeout"}


def test_direct_timeout_error_does_not_include_input(monkeypatch: pytest.MonkeyPatch) -> None:
    def stalled(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["private-input"], 90)

    monkeypatch.setattr(http, "run_process", stalled)
    with pytest.raises(ProbeError, match="总期限") as captured:
        http.forward_messages("deepseek", "private-key", b"private-prompt")
    assert "private" not in str(captured.value)

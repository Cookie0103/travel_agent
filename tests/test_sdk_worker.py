"""SDK 工作进程边界：凭据隔离与结果分类，错误和取消不能当成功。"""

from pathlib import Path

import pytest
from claude_agent_sdk import ResultMessage

from backend.providers.probe.settings import ProbeError
from backend.providers.sdk_probe.environment import find_cli, find_git_bash, worker_environment
from backend.providers.sdk_probe.worker import result_summary


def test_sdk_worker_does_not_inherit_real_credentials(tmp_path: Path) -> None:
    source = {
        "PATH": "system-path",
        "DEEPSEEK_API_KEY": "real-secret",
        "ANTHROPIC_API_KEY": "dollar-secret",
        "CLAUDE_CODE_OAUTH_TOKEN": "user-token",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "HTTP_PROXY": "external-proxy",
        "NODE_OPTIONS": "--require unknown.js",
        "OTEL_EXPORTER_OTLP_HEADERS": "secret",
    }
    env = worker_environment(
        source,
        tmp_path / "private",
        tmp_path,
        "http://127.0.0.1:12",
        "local-token",
        "deepseek-flash",
    )
    assert "real-secret" not in str(env) and "dollar-secret" not in str(env)
    assert not set(source).difference({"PATH"}).intersection(env)
    assert env["ANTHROPIC_AUTH_TOKEN"] == "local-token"
    assert env["CLAUDE_CODE_MAX_RETRIES"] == "0"


def test_missing_cli_is_explicit(tmp_path: Path) -> None:
    with pytest.raises(ProbeError, match="CLI"):
        find_cli({"TRAVEL_CLAUDE_CLI": str(tmp_path / "missing.exe")})


@pytest.mark.parametrize("git_location", ["cmd", "mingw64/bin"])
def test_git_bash_is_found_for_shell_and_hook_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_location: str
) -> None:
    git = tmp_path / git_location / "git.exe"
    git.parent.mkdir(parents=True)
    git.touch()
    bash = tmp_path / "bin" / "bash.exe"
    bash.parent.mkdir()
    bash.touch()
    monkeypatch.setattr("shutil.which", lambda *args, **kwargs: str(git))
    assert find_git_bash({"PATH": str(git.parent)}) == bash


def test_missing_explicit_git_bash_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProbeError, match="Git Bash"):
        find_git_bash({"CLAUDE_CODE_GIT_BASH_PATH": str(tmp_path / "missing.exe")})


@pytest.mark.parametrize(
    "reason", ["max_turns", "aborted_streaming", "aborted_tools", "future_reason"]
)
def test_terminal_reason_overrides_success_subtype(reason: str) -> None:
    """R02：半条流、取消、达到轮次上限都不能当完成。"""
    result = ResultMessage(
        "success", 1, 1, False, 1, "session", result="kyoto-sdk-ok", terminal_reason=reason
    )
    assert result_summary(result, ["echo"], ["ResultMessage"], "kyoto-sdk-ok")["status"] == "error"


def test_success_requires_tool_execution_and_final_result() -> None:
    result = ResultMessage(
        "success", 1, 1, False, 1, "session", result="kyoto-sdk-ok", terminal_reason="completed"
    )
    assert result_summary(result, [], ["ResultMessage"], "kyoto-sdk-ok")["status"] == "error"
    assert (
        result_summary(result, ["echo"], ["ResultMessage"], "kyoto-sdk-ok")["status"] == "success"
    )
    assert (
        result_summary(result, ["echo"], [], "kyoto-sdk-ok:unseen-challenge")["status"] == "error"
    )

"""固定版本获取的离线测试：不使用网络，不修改真实 vendor 目录。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import fetch_upstream as upstream


def test_existing_pinned_repository_is_not_cloned_or_reset(tmp_path: Path) -> None:
    source = upstream.UPSTREAMS[0]
    (tmp_path / source.name / ".git").mkdir(parents=True)
    with patch.object(upstream, "git", return_value=source.commit) as git:
        upstream.fetch(source, tmp_path)
    assert git.call_count == 1
    assert git.call_args.args[-2:] == ("rev-parse", "HEAD")


def test_wrong_existing_commit_is_rejected_without_reset(tmp_path: Path) -> None:
    source = upstream.UPSTREAMS[0]
    (tmp_path / source.name / ".git").mkdir(parents=True)
    with patch.object(upstream, "git", return_value="wrong-commit") as git:
        with pytest.raises(upstream.FetchError, match="conflict"):
            upstream.fetch(source, tmp_path)
    assert git.call_count == 1


def test_existing_non_repository_is_preserved(tmp_path: Path) -> None:
    source = upstream.UPSTREAMS[0]
    (tmp_path / source.name).mkdir()
    with patch.object(upstream, "git") as git:
        with pytest.raises(upstream.FetchError, match="不是 Git 仓库"):
            upstream.fetch(source, tmp_path)
    git.assert_not_called()


def test_new_repository_is_checked_out_to_exact_commit(tmp_path: Path) -> None:
    source = upstream.UPSTREAMS[0]
    with patch.object(upstream, "git", side_effect=["", "", source.commit]) as git:
        upstream.fetch(source, tmp_path)
    assert git.call_args_list[0].args[0] == "clone"
    assert git.call_args_list[1].args[-3:] == ("checkout", "--detach", source.commit)


def test_wrong_commit_after_checkout_is_rejected(tmp_path: Path) -> None:
    with patch.object(upstream, "git", side_effect=["", "", "wrong-commit"]):
        with pytest.raises(upstream.FetchError, match="checkout 后版本不符"):
            upstream.fetch(upstream.UPSTREAMS[0], tmp_path)


def test_required_upstream_failure_stops_the_command() -> None:
    with patch.object(upstream, "fetch", side_effect=upstream.FetchError("unavailable")) as fetch:
        assert upstream.main() == 1
    assert fetch.call_count == 1


def test_optional_upstream_failure_warns_and_allows_completion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch.object(upstream, "fetch", side_effect=[None, upstream.FetchError("unavailable")]):
        assert upstream.main() == 0
    assert "warning: datamind-ai-agent" in capsys.readouterr().err


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("git", 1)])
def test_git_missing_or_timeout_has_a_classified_error(error: Exception) -> None:
    with patch("scripts.fetch_upstream.subprocess.run", side_effect=error):
        with pytest.raises(upstream.FetchError, match="unavailable|timeout"):
            upstream.git("--version")


def test_git_failure_does_not_echo_credential_bearing_output() -> None:
    result = subprocess.CompletedProcess([], 128, stdout="", stderr="credential-like-value")
    with patch("scripts.fetch_upstream.subprocess.run", return_value=result):
        with pytest.raises(upstream.FetchError) as exc:
            upstream.git("clone")
    assert "credential-like-value" not in str(exc.value)


def test_git_disables_interactive_credential_prompts() -> None:
    result = subprocess.CompletedProcess([], 0, stdout="commit\n", stderr="")
    with patch("scripts.fetch_upstream.subprocess.run", return_value=result) as run:
        assert upstream.git("rev-parse", "HEAD") == "commit"
    assert run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert run.call_args.kwargs["env"]["GCM_INTERACTIVE"] == "never"

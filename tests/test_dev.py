"""开发入口的失败路径：检查失败停止、离线门禁以及环境阻塞可恢复。"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import dev


def test_failed_check_stops_before_following_commands() -> None:
    with patch.object(dev, "run_command", return_value=7) as run:
        assert dev.main(["check"]) == 7
    assert run.call_count == 1
    assert run.call_args.args[0][-2:] == ["check", "."]


def test_failed_sync_does_not_install_commit_hook() -> None:
    with patch.object(dev, "run_command", return_value=2) as run:
        assert dev.main(["setup"]) == 2
    assert run.call_count == 1
    assert run.call_args.args[0] == ["uv", "sync", "--locked"]


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("tool", 1)])
def test_unavailable_or_timed_out_command_returns_failure(error: Exception) -> None:
    with patch("scripts.dev.subprocess.run", side_effect=error):
        assert dev.run_command(["missing-tool"]) == 1


def test_child_process_inherits_utf8_and_repository_working_directory() -> None:
    dev.configure_environment()
    assert os.environ["PYTHONUTF8"] == "1"
    with patch(
        "scripts.dev.subprocess.run", return_value=subprocess.CompletedProcess([], 0)
    ) as run:
        assert dev.run_command(["tool"]) == 0
    assert run.call_args.kwargs["cwd"] == dev.ROOT


def test_offline_test_command_cannot_enable_live_tests() -> None:
    with patch.object(dev, "run_command", return_value=0) as run:
        assert dev.main(["test"]) == 0
    assert run.call_args.args[0][:5] == [sys.executable, "-m", "pytest", "-m", "not live"]
    with pytest.raises(SystemExit) as exc:
        dev.main(["test", "--live"])
    assert exc.value.code == 2


def test_failed_test_runs_isolate_temp_and_cache_without_touching_old_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    old_file = tmp_path / "existing.txt"
    old_file.write_text("保留旧现场", encoding="utf-8")
    monkeypatch.setenv("PYTEST_DEBUG_TEMPROOT", str(tmp_path))
    runs: list[Path] = []

    def fail(command: Sequence[str]) -> int:
        directory = Path(os.environ["PYTEST_DEBUG_TEMPROOT"])
        runs.append(directory)
        assert directory.is_relative_to(tmp_path / ".cache" / "pytest-runs")
        assert command[-2] == "-o"
        assert command[-1] == f"cache_dir={directory / 'cache'}"
        return 3

    monkeypatch.setattr(dev, "run_command", fail)
    assert dev.main(["test"]) == 3
    assert dev.main(["test"]) == 3
    assert runs[0] != runs[1]
    assert all(directory.is_dir() for directory in runs)
    assert os.environ["PYTEST_DEBUG_TEMPROOT"] == str(tmp_path)
    assert old_file.read_text(encoding="utf-8") == "保留旧现场"


def test_unwritable_test_directory_fails_before_starting_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    with patch("scripts.dev.tempfile.mkdtemp", side_effect=PermissionError):
        with patch.object(dev, "run_command") as run:
            assert dev.main(["test"]) == 1
    run.assert_not_called()


def test_stopped_docker_records_blocker_without_running_compose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    with patch.object(dev, "run_command", return_value=1) as run:
        assert dev.main(["db-up"]) == 1
        assert dev.main(["db-up"]) == 1
    assert run.call_count == 2
    assert all(call.args[0][1] == "info" for call in run.call_args_list)
    report = tmp_path / "docs" / "blocked" / "environment.md"
    assert report.read_text(encoding="utf-8").count("Docker 引擎不可用") == 1
    assert not (tmp_path / "BLOCKED.md").exists()


def test_available_docker_starts_only_postgres() -> None:
    with patch.object(dev, "run_command", return_value=0) as run:
        assert dev.main(["db-up"]) == 0
    assert run.call_count == 2
    assert run.call_args.args[0][-1] == "postgres"


@pytest.mark.parametrize("args", [["eval-dev"], ["eval-dev", "--live"]])
def test_unimplemented_evaluation_fails_without_starting_a_process(
    args: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    with patch.object(dev, "run_command") as run:
        assert dev.main(args) == 1
    run.assert_not_called()

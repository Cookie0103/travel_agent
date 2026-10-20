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


def test_explicit_webpack_build_still_runs_every_frontend_gate() -> None:
    with patch("scripts.dev.shutil.which", return_value="pnpm"):
        with patch.object(dev, "run_command", return_value=0) as run:
            assert dev.main(["web-check", "--webpack"]) == 0
            assert [call.args[0] for call in run.call_args_list] == [
                ["pnpm", "run", "typecheck"],
                ["pnpm", "run", "lint"],
                ["pnpm", "run", "test"],
                ["pnpm", "run", "build", "--webpack"],
            ]


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


def test_scoped_tests_keep_offline_marker_and_fixed_argument_boundaries() -> None:
    """专项选择仍经过项目入口，不能覆盖 live 门禁或注入 pytest 参数。"""
    with patch.object(dev, "run_command", return_value=7) as run:
        assert dev.main(["test", "--path", "tests/test_dev.py", "--keyword", "budget"]) == 7
    command = run.call_args.args[0]
    assert command[:5] == [sys.executable, "-m", "pytest", "-m", "not live"]
    assert "tests/test_dev.py" in command
    assert command[command.index("-k") + 1] == "budget"
    for path in ("../outside.py", "--live", "scripts/dev.py"):
        with pytest.raises(SystemExit) as exc:
            dev.main(["test", "--path", path])
        assert exc.value.code == 2


def test_project_formatter_edits_python_and_preserves_other_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    code = tmp_path / "sample.py"
    data = tmp_path / "sample.json"
    code.write_text("x= 1\n", encoding="utf-8")
    data.write_text('{"x":1}', encoding="utf-8")
    assert dev.main(["format"]) == 0
    assert code.read_text(encoding="utf-8") == "x = 1\n"
    assert data.read_text(encoding="utf-8") == '{"x":1}'


def test_local_api_live_and_trace_require_explicit_flags() -> None:
    with patch.object(dev, "run_command", return_value=0) as run:
        assert dev.main(["api"]) == 0
        assert run.call_args.args[0] == [sys.executable, "-m", "backend.server"]
        assert dev.main(["api", "--live", "--trace-cloud"]) == 0
        assert run.call_args.args[0] == [
            sys.executable,
            "-m",
            "backend.server",
            "--live",
            "--trace-cloud",
        ]


def test_hotel_sort_probe_requires_explicit_live_flag() -> None:
    with patch.object(dev, "run_command", return_value=0) as run:
        assert dev.main(["probe-hotel-sort"]) == 2
        run.assert_not_called()
        assert dev.main(["probe-hotel-sort", "--live"]) == 0
        assert run.call_args.args[0] == [sys.executable, "-m", "scripts.probe_hotel_sort", "--live"]


def test_langfuse_smoke_requires_both_explicit_authorization_flags() -> None:
    with patch.object(dev, "run_command", return_value=0) as run:
        for flags in ([], ["--live"], ["--trace-cloud"]):
            assert dev.main(["smoke-langfuse-linkage", *flags]) == 2
            run.assert_not_called()
        assert dev.main(["smoke-langfuse-linkage", "--live", "--trace-cloud"]) == 0
        assert run.call_args.args[0][-3:] == [
            "scripts.smoke_langfuse_linkage",
            "--live",
            "--trace-cloud",
        ]


def test_v2_eval_default_is_offline_and_cloud_needs_live() -> None:
    with patch.object(dev, "run_command", return_value=0) as run:
        assert dev.main(["eval-v2", "--trace-cloud"]) == 2
        run.assert_not_called()
        assert dev.main(["eval-v2"]) == 0
        assert "--live" not in run.call_args.args[0]
        assert "--database" in run.call_args.args[0]


def test_failed_test_runs_isolate_temp_and_cache_without_touching_old_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    old_file = tmp_path / "existing.txt"
    old_file.write_text("保留旧现场", encoding="utf-8")
    monkeypatch.setenv("PYTEST_DEBUG_TEMPROOT", str(tmp_path))
    runs: list[Path] = []

    def fail(command: Sequence[str], *, timeout: int | None = 300) -> int:
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


def test_full_offline_suite_keeps_failure_exit_after_long_but_bounded_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R08：整套测试超过五分钟也须跑完；失败仍返回原退出码，不设无限等待。"""
    monkeypatch.setattr(dev, "ROOT", tmp_path)

    def elapsed_suite(
        command: Sequence[str], **options: object
    ) -> subprocess.CompletedProcess[str]:
        timeout = options["timeout"]
        assert isinstance(timeout, int) and 0 < timeout <= 900
        if timeout < 310:
            raise subprocess.TimeoutExpired(command, timeout)
        return subprocess.CompletedProcess(command, 7)

    with patch("scripts.dev.subprocess.run", side_effect=elapsed_suite):
        assert dev.main(["test"]) == 7


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


def test_web_formatter_uses_existing_package_script() -> None:
    with (
        patch("scripts.dev.shutil.which", return_value="pnpm"),
        patch.object(dev, "run_command", return_value=0) as run,
    ):
        assert dev.main(["web-format"]) == 0
    assert run.call_args.args[0] == ["pnpm", "run", "format"]
    assert run.call_args.kwargs["cwd"] == dev.ROOT / "apps" / "web"


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


def test_pinned_cli_is_read_from_env_file_without_overriding_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("TRAVEL_CLAUDE_CLI=/pinned/claude.exe\nOTHER=1\n", "utf-8")
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    monkeypatch.setenv("TRAVEL_CLAUDE_CLI", "")  # 让 monkeypatch 负责收尾还原
    monkeypatch.delenv("TRAVEL_CLAUDE_CLI")
    dev.pinned_cli()
    assert os.environ["TRAVEL_CLAUDE_CLI"] == "/pinned/claude.exe"
    assert "OTHER" not in os.environ
    monkeypatch.setenv("TRAVEL_CLAUDE_CLI", "/explicit")
    dev.pinned_cli()
    assert os.environ["TRAVEL_CLAUDE_CLI"] == "/explicit"

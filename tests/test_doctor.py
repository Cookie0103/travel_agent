"""dev doctor：一次列出本机前置条件，失败项带修复提示且退出码非零。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import dev, doctor

GOOD: dict[str, str | None] = {
    "node": "v24.3.0",
    "pnpm": "11.19.0",
    "uv": "uv 0.9.0",
    "claude": "2.1.295 (Claude Code)",
}


def reader(outputs: dict[str, str | None]) -> Callable[[Sequence[str]], str | None]:
    def read(command: Sequence[str]) -> str | None:
        return outputs.get(command[0])

    return read


def by_name(results: list[doctor.Check]) -> dict[str, doctor.Check]:
    return {item.name: item for item in results}


def test_tool_versions_pass_when_supported() -> None:
    results = by_name(doctor.tool_checks(reader(GOOD)))
    assert all(item.ok for item in results.values()), results


@pytest.mark.parametrize(
    ("tool", "output", "hint"),
    [
        ("node", "v22.1.0", "Node 24"),
        ("pnpm", "10.2.0", "pnpm 11"),
        ("uv", None, "uv"),
        ("claude", "2.1.302 (Claude Code)", "2.1.295"),
        ("claude", None, "claude-code"),
    ],
)
def test_unsupported_tool_reports_actionable_hint(tool: str, output: str | None, hint: str) -> None:
    results = by_name(doctor.tool_checks(reader({**GOOD, tool: output})))
    failed = results[tool]
    assert not failed.ok and hint in failed.hint
    if output:
        assert output.split()[0].lstrip("v") in failed.detail


def test_unwritable_temp_root_is_reported(tmp_path: Path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("x")
    result = doctor.temp_check(blocked / "pytest-tmp")
    assert not result.ok and "PYTEST_DEBUG_TEMPROOT" in result.hint
    assert doctor.temp_check(tmp_path / "ok").ok


def test_postgres_unreachable_hints_db_up() -> None:
    with patch("scripts.doctor.socket.create_connection", side_effect=OSError):
        result = doctor.postgres_check({"POSTGRES_PORT": "5434"})
    assert not result.ok and "db-up" in result.hint and "5434" in result.detail


def test_main_exit_code_and_dev_subcommand() -> None:
    bad = [doctor.Check("node", False, "v22", "安装 Node 24")]
    with patch.object(doctor, "run_checks", return_value=bad):
        assert doctor.main() == 1
    with patch.object(doctor, "run_checks", return_value=[doctor.Check("x", True, "ok", "")]):
        assert doctor.main() == 0
    with patch.object(dev, "run_command", return_value=3) as run:
        assert dev.main(["doctor"]) == 3
    assert run.call_args.args[0][-2:] == ["-m", "scripts.doctor"]

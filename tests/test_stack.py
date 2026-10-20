"""独立演示配置复用且不覆盖损坏/已有凭据；不调用Docker或模型。"""

from pathlib import Path

import pytest

from scripts import stack
from scripts.stack import main, settings


def test_generated_demo_password_is_reused_without_reading_user_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=private-canary", encoding="utf-8")
    path = settings(tmp_path)
    original = path.read_bytes()
    assert b"private-canary" not in original and len(original) == 82
    assert settings(tmp_path) == path and path.read_bytes() == original


def test_corrupt_demo_settings_are_preserved_and_rejected(tmp_path: Path) -> None:
    path = tmp_path / ".cache/demo.env"
    path.parent.mkdir()
    path.write_text("DEMO_DB_PASSWORD=wrong\n", encoding="utf-8")
    with pytest.raises(ValueError, match="配置损坏"):
        settings(tmp_path)
    assert path.read_text(encoding="utf-8") == "DEMO_DB_PASSWORD=wrong\n"
    assert main("invalid") == 2


@pytest.mark.parametrize("failure", ["daemon", "build", "none"])
def test_failed_daemon_or_build_never_starts_containers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], *, timeout: int) -> int:
        commands.append(command)
        return int(
            (failure == "daemon" and command[1] == "info")
            or (failure == "build" and command[-1] == "build")
        )

    monkeypatch.setattr(stack, "settings", lambda: settings(tmp_path))
    monkeypatch.setattr(stack, "run_command", run)
    assert main("stack-up") == int(failure != "none")
    assert len(commands) == {"daemon": 1, "build": 2, "none": 3}[failure]
    if failure != "daemon":
        assert commands[1][-1] == "build"
    if failure == "none":
        assert commands[2][-5:] == ["up", "-d", "--wait", "--wait-timeout", "180"]
    assert all("--project-name" in command for command in commands[1:])


def test_stop_preserves_volumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], *, timeout: int) -> int:
        commands.append(command)
        return 0

    monkeypatch.setattr(stack, "settings", lambda: settings(tmp_path))
    monkeypatch.setattr(stack, "run_command", run)
    assert main("stack-down") == 0
    assert commands[-1][-1] == "down"
    assert not {"-v", "--volumes", "--remove-orphans"}.intersection(commands[-1])

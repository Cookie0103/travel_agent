"""CLI 默认离线；环境里存在密钥也不能隐式开启付费调用。"""

import sys

import pytest

from backend.cli import main


def test_cli_default_does_not_use_live_provider(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*args: object) -> None:
        raise AssertionError("default CLI must not invoke live")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured-but-unused")
    monkeypatch.setattr("backend.cli.run_live", forbidden)
    monkeypatch.setattr(sys, "argv", ["travel-agent", "京都有哪些室内景点？"])
    assert main() == 0
    text = capsys.readouterr().out
    assert "离线演示" in text and "fixture:kyoto-v1" in text
    assert "configured-but-unused" not in text


def test_explicit_live_without_key_fails_before_worker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["travel-agent", "--live", "京都"])
    assert main() == 1
    assert "未配置" in capsys.readouterr().out


def test_offline_trace_failure_preserves_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("private disk path")

    monkeypatch.setattr("backend.adapters.tracing.write_trace", fail)
    monkeypatch.setattr(sys, "argv", ["travel-agent", "京都有哪些室内景点？"])
    assert main() == 0
    text = capsys.readouterr().out
    assert "离线演示" in text and "记录失败" in text and "private disk path" not in text

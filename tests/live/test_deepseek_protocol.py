"""M0.2 显式 live 入口：只跑一次有费用与次数上限的工具往返。"""

import os
from pathlib import Path

import pytest

from backend.providers.probe.flow import run_probe
from backend.providers.probe.settings import load_settings

pytestmark = pytest.mark.live


def test_deepseek_streamed_tool_roundtrip() -> None:
    """R02：流式工具参数完成、结果 ID 配对后可带完整原消息续接。"""
    settings = load_settings(os.environ)
    root = Path(__file__).resolve().parents[2]
    report = run_probe(settings, root / ".cache" / "m02-protocol")
    assert report["status"] == "success"

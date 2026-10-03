"""M0.2 显式真实 SDK 验收；累积 5 元/100 次且逐请求预占。"""

import os
from pathlib import Path

import pytest

from backend.providers.probe.settings import load_settings
from backend.providers.sdk_probe.flow import run_probe

pytestmark = pytest.mark.live


def test_sdk_deepseek_tool_roundtrip() -> None:
    """R02：实际 SDK 执行一个合成只读工具并回填结果。"""
    report = run_probe(load_settings(os.environ), Path(__file__).resolve().parents[2])
    assert report["status"] == "success", report
    attempts = report["http_attempts"]
    assert isinstance(attempts, int) and attempts >= 2

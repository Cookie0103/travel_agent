"""测试会话配置：隔离临时目录，固定离线测试的旅行日历。"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.support.clock import FIXTURE_TODAY, FIXTURE_TODAY_ENV, fixture_travel_calendar


def pytest_configure() -> None:
    # 系统临时目录的 pytest-of-<user> 可能被其他账户/沙箱占用而 PermissionError；
    # 显式设置（如 scripts/dev.py test 的每次运行目录）时不覆盖。
    if "PYTEST_DEBUG_TEMPROOT" not in os.environ:
        root = Path(__file__).resolve().parents[1] / ".cache" / "pytest-tmp"
        root.mkdir(parents=True, exist_ok=True)
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(root)


@pytest.fixture(autouse=True)
def fixed_today(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if request.node.get_closest_marker("live") is not None:
        yield
        return
    monkeypatch.setenv(FIXTURE_TODAY_ENV, FIXTURE_TODAY.isoformat())
    with fixture_travel_calendar():
        yield


@pytest.fixture
def allow_mocked_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式放行eval入口的--live防护：仅用于已把真实调用全部打桩/禁止的测试。"""
    monkeypatch.setenv("TRAVEL_ALLOW_LIVE_IN_TESTS", "1")

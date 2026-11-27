"""用模拟的 2030 年宿主时钟验证离线测试的行程日期夹具。"""

import subprocess
import sys
from pathlib import Path

_SIMULATE_2030 = """
import sys
from datetime import datetime

import pytest

from backend.domain import travel_request


class HostDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2030, 1, 1, 12, tzinfo=tz)


travel_request.datetime = HostDatetime
assert travel_request.tokyo_today().year == 2030
raise SystemExit(pytest.main(sys.argv[1:]))
"""


def test_trip_fixture_survives_2030_host_clock(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    test_node = (
        "tests/unit/domain/test_travel_request.py"
        "::test_segment_patch_derives_globals_preserves_revision_and_explicit_clear"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            _SIMULATE_2030,
            test_node,
            "-q",
            "-o",
            f"cache_dir={tmp_path / 'cache'}",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

"""裸跑 pytest 也不依赖系统临时目录权限（本机 pytest-of-user 曾 PermissionError）。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_probe(tmp_path_factory: pytest.TempPathFactory) -> None:
    if not os.environ.get("TMP_ROOT_PROBE"):
        pytest.skip("仅由 test_bare_pytest_uses_project_cache 子进程执行")
    print(f"BASETEMP={tmp_path_factory.getbasetemp()}")


def test_bare_pytest_uses_project_cache() -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_DEBUG_TEMPROOT"}
    env["TMP_ROOT_PROBE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            f"{__file__}::test_probe",
            "-q",
            "-s",
            "-p",
            "no:cacheprovider",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    line = next(item for item in result.stdout.splitlines() if item.startswith("BASETEMP="))
    assert Path(line.removeprefix("BASETEMP=")).is_relative_to(ROOT / ".cache")

"""使用无网络的探针测试默认 pytest 命令确实排除 live，而非只检查配置文本。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_default_pytest_deselects_live_probe(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    # Windows 临时目录可能在另一盘；配置跟探针放一起，避免 pytest 扫描用户目录。
    config = tmp_path / "pyproject.toml"
    config.write_text((root / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8")
    probe = tmp_path / "test_marker_probe.py"
    probe.write_text(
        "import pytest\n\n"
        "def test_offline():\n    assert True\n\n"
        "@pytest.mark.live\n"
        "def test_live_probe():\n    raise AssertionError('live must be deselected')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", str(config), str(probe), "-q"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 1 deselected" in result.stdout

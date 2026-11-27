"""父子进程stdin交接：任意大小载荷（含>64KiB管道容量）必须完整送达。"""

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from backend.providers.claude_agent.process import run_process

READER = (
    "import time;time.sleep(0.6);"
    "import hashlib,sys;d=sys.stdin.buffer.read();"
    "print(len(d),hashlib.sha256(d).hexdigest())"
)


@pytest.mark.parametrize("size", [1, 65_535, 65_536, 65_537, 70_000, 200_000])
def test_stdin_payload_delivered_intact(size: int, tmp_path: Path) -> None:
    payload = "é" * (size // 2) + "x" * (size % 2)  # 含多字节字符
    raw = payload.encode()
    result = run_process([sys.executable, "-c", READER], tmp_path, {}, 5, payload)
    assert result.stdout.split() == [str(len(raw)), hashlib.sha256(raw).hexdigest()]


def test_stalled_child_is_still_killed_at_deadline(tmp_path: Path) -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, "-c", "import time;time.sleep(60)"], tmp_path, {}, 1, "x")

"""R17：实际进程互斥和崩溃恢复；不调用模型，不更改费用账本。"""

import subprocess
import sys
import time
from pathlib import Path

import pytest

from backend.limits import ProbeError
from backend.providers.claude_agent.ledger import exclusive


def test_legacy_marker_without_owner_does_not_block_and_ledger_is_untouched(tmp_path: Path) -> None:
    marker = tmp_path / "active.lock"
    marker.write_text("M0.2 running\n", encoding="utf-8")
    ledger = tmp_path / "deepseek.jsonl"
    ledger.write_bytes(b'{"kind":"attempt","charge_cny":"0.42"}\n')
    before = ledger.read_bytes()
    with exclusive(marker):
        assert ledger.read_bytes() == before
    with exclusive(marker):
        assert ledger.read_bytes() == before


def acquire_after_owner_death(marker: Path) -> None:
    """Windows在进程对象已触发后才异步释放其字节范围锁（实测滞后约0-2ms），故有界轮询而非立即断言。"""
    deadline = time.monotonic() + 5
    while True:
        try:
            with exclusive(marker):
                return
        except ProbeError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.005)


def test_live_process_blocks_competitor_but_killed_owner_releases_lock(tmp_path: Path) -> None:
    marker = tmp_path / "active.lock"
    root = Path(__file__).resolve().parents[1]
    script = (
        "from pathlib import Path\n"
        "from backend.providers.claude_agent.ledger import exclusive\n"
        "import sys\n"
        "with exclusive(Path(sys.argv[1])):\n"
        " print('locked', flush=True)\n"
        " sys.stdin.read()\n"
    )
    with subprocess.Popen(
        [sys.executable, "-c", script, str(marker)],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        try:
            assert process.stdout is not None and process.stdout.readline().strip() == "locked"
            with pytest.raises(ProbeError, match="正在运行"):
                with exclusive(marker):
                    pytest.fail("An active process must exclude another run")
            process.kill()  # 模拟部署强制终止，Python finally没有执行机会
            process.wait(timeout=10)
            acquire_after_owner_death(marker)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)

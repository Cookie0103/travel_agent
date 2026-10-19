"""实测前持久计次和占用保守费用；失败及中断不退回次数或费用。"""

import errno
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.limits import Currency, ProbeError, read_budget
from backend.trace_log import trace

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


@dataclass(frozen=True)
class Entry:
    """账本只保存计数和金额，不保存请求正文或认证信息。"""

    kind: str
    day: str
    currency: Currency
    charge: str = "0"


@contextmanager
def exclusive(path: Path) -> Iterator[None]:
    """内核持有互斥直到句柄关闭/进程退出；磁盘标记不代表仍有活跃执行。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    # 不变量：不unlink，否则等待者与新请求可能分别锁住旧/新inode而同时进入。
    with path.open("a+b") as handle:
        try:
            if sys.platform == "win32":
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                trace("live_lock_rejected", reason="busy")
                raise ProbeError("blocked", "已有执行正在运行，请等待其结束") from None
            raise ProbeError("unavailable", "无法获取执行锁，未发起模型调用") from None
        try:
            yield
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_jsonl(path: Path) -> list[object]:
    """两个账本共用的读取边界：文件不存在返回空；坏行抛 ValueError，由调用方拒绝自动重跑。"""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def append_line(path: Path, record: dict[str, object]) -> None:
    """两个账本唯一的落盘方式：先 fsync 才联网；崩溃时已落盘行保留全部预占。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


class Ledger:
    """调用方须持有流程锁；日额度按 UTC，批次次数不按日重置。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def entries(self) -> list[Entry]:
        entries: list[Entry] = []
        try:
            for record in read_jsonl(self.path):
                if not isinstance(record, dict) or set(record) != {
                    "kind",
                    "day",
                    "currency",
                    "charge",
                }:
                    raise ValueError
                if record["kind"] not in {"flow", "attempt", "success"}:
                    raise ValueError
                if record["currency"] not in {"CNY", "USD"}:
                    raise ValueError
                if not isinstance(record["day"], str) or not isinstance(record["charge"], str):
                    raise ValueError
                datetime.strptime(record["day"], "%Y-%m-%d")
                read_budget(record["charge"])
                entries.append(
                    Entry(record["kind"], record["day"], record["currency"], record["charge"])
                )
        except (ValueError, TypeError, ProbeError):
            raise ProbeError("blocked", "账本损坏，禁止清空后自动重跑") from None
        return entries

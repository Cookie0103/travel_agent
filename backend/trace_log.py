"""Railway 可见的单行 `TRACE {json}`；只记元数据（数字/短标识），不记正文、密钥或带查询串的 URL。

永不抛错。子进程（SDK worker/转发器）的 stdout 是 JSON 报告，不能写 TRACE：有 TRAVEL_TRACE_FILE
时追加到该文件，由父进程的 Tail 轮询后转印到自己的 stdout；否则静默。
API进程在 server 入口调用 enable_stdout() 才向 stdout 输出。
"""

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

FILE_ENV, RUN_ENV = "TRAVEL_TRACE_FILE", "TRAVEL_TRACE_RUN"
_TEXT_KEYS = re.compile(
    r"key|token|secret|auth|password|prompt|text|body|content|query|url|header", re.I
)
_stdout = False  # 仅API进程显式开启；worker/转发器的stdout是JSON结果，默认静默


def enable_stdout() -> None:
    global _stdout
    _stdout = True


def _clean(key: str, value: object) -> object:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return round(value, 3)
    if _TEXT_KEYS.search(key):
        return "[dropped]"
    if isinstance(value, dict):  # 仅限额这类小型数字表；文本值仍按键名脱敏
        return {str(k)[:30]: _clean(str(k), v) for k, v in list(value.items())[:16]}
    if isinstance(value, str):
        return "[redacted]" if "://" in value or "?" in value else value[:80]
    if isinstance(value, list | tuple):  # 仅名称列表（如工具名）
        return [item[:60] for item in value[:8] if isinstance(item, str) and "://" not in item]
    return "[dropped]"


def trace(ev: str, run: object = None, **fields: object) -> None:
    try:
        now = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        record: dict[str, object] = {
            "ts": now,
            "run": str(run or os.environ.get(RUN_ENV, ""))[:8],
            "ev": ev,
        }
        record.update({key: _clean(key, value) for key, value in fields.items()})
        line = "TRACE " + json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        path = os.environ.get(FILE_ENV)
        if path:
            with open(path, "a", encoding="utf-8", newline="\n") as stream:
                stream.write(line)
        elif _stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
    except Exception:  # 诊断日志不得影响请求路径
        pass


class Tail:
    """父进程轮询子进程 trace 文件，把已写完整的行转印到自己的 stdout。"""

    def __init__(self, path: Path) -> None:
        self.path, self.offset = path, 0

    def drain(self) -> None:
        try:
            with self.path.open("rb") as stream:
                stream.seek(self.offset)
                data = stream.read()
            complete = data[: data.rfind(b"\n") + 1]
            self.offset += len(complete)
            lines = [
                x
                for x in complete.decode("utf-8", "replace").splitlines()
                if x.startswith("TRACE ")
            ]
            if lines:
                sys.stdout.write("\n".join(lines) + "\n")
                sys.stdout.flush()
        except Exception:
            pass

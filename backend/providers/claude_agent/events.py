"""受控SDK进程的私有事件日志；父进程逐行读取以持久化UI进度，不重跑工具。"""

import json
from dataclasses import asdict
from pathlib import Path

from pydantic import TypeAdapter

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeEvent

EVENT = TypeAdapter(RuntimeEvent)


class EventReader:
    def __init__(self, path: Path, context: RunContext, emit: EventSink | None) -> None:
        self.path, self.context, self.emit = path, context, emit
        self.offset = 0

    def drain(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as stream:
            stream.seek(self.offset)
            while line := stream.readline(65537):
                if len(line) > 65536:
                    raise ValueError("SDK事件超过长度上限")
                if not line.endswith("\n"):
                    break
                event = EVENT.validate_json(line)
                if event.context != self.context:
                    raise ValueError("SDK事件身份不匹配")
                if self.emit is not None and event.kind not in {"completed", "failed", "cancelled"}:
                    self.emit(event)
                self.offset = stream.tell()


def save_event(path: Path, event: RuntimeEvent) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(asdict(event), ensure_ascii=False, default=str) + "\n")
        stream.flush()

"""私有进度日志只能转发当前run的完整记录；父进程验证前不能公开成功。"""

import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeEvent
from backend.providers.claude_agent.events import EventReader, save_event


def test_partial_event_is_read_once_and_worker_terminal_is_withheld(tmp_path: Path) -> None:
    context = RunContext(uuid4())
    path = tmp_path / "events.jsonl"
    received: list[RuntimeEvent] = []
    reader = EventReader(path, context, received.append)
    reader.drain()
    first = RuntimeEvent(context, "text", text="京都进度")
    serialized = json.dumps(asdict(first), ensure_ascii=False, default=str)
    path.write_text(serialized, encoding="utf-8")
    reader.drain()
    assert not received
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n")
    save_event(path, RuntimeEvent(context, "completed"))
    reader.drain()
    reader.drain()
    assert received == [first]


def test_foreign_event_is_rejected_before_callback(tmp_path: Path) -> None:
    received: list[RuntimeEvent] = []
    path = tmp_path / "events.jsonl"
    save_event(path, RuntimeEvent(RunContext(uuid4()), "text", text="other user"))
    with pytest.raises(ValueError, match="身份"):
        EventReader(path, RunContext(uuid4()), received.append).drain()
    assert not received

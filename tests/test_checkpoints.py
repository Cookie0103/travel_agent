"""私有续接元数据边界；实际SDK文件/进程测试见integration/test_sdk_recovery。"""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeIdentity, SessionReference
from backend.providers.claude_agent.checkpoints import Checkpoints


def test_checkpoint_identity_revision_foreign_owner_and_corruption_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = Checkpoints(tmp_path)
    context = RunContext(uuid4())
    identity = RuntimeIdentity("deepseek", "deepseek-flash", "sdk", "cli")
    reference = SessionReference(context, identity, str(uuid4()))
    monkeypatch.setattr(checkpoint, "_digest", lambda sdk_id: "a" * 64)
    assert checkpoint.save(reference, 1)
    assert checkpoint.load(replace(context, run_id=uuid4()), identity, 1) == reference
    for foreign in (replace(context, user_id=uuid4()), replace(context, session_id=uuid4())):
        assert checkpoint.load(foreign, identity, 1) is None
    assert checkpoint.load(context, identity, 2) is None
    assert checkpoint.load(context, identity, 1, preference_revision=1) is None
    assert checkpoint.save(reference, 1, preference_revision=2)
    assert checkpoint.load(context, identity, 1, preference_revision=2) == reference
    assert checkpoint.load(context, identity, 1, preference_revision=3) is None
    assert checkpoint.save(reference, 1)
    assert checkpoint.load(context, replace(identity, model="other"), 1) is None
    monkeypatch.setattr(checkpoint, "_digest", lambda sdk_id: "b" * 64)
    assert checkpoint.load(context, identity, 1) is None
    checkpoint.path.write_text("x" * (64 * 1024 + 1), encoding="utf-8")
    assert checkpoint.load(context, identity, 1) is None
    checkpoint.path.write_text('{"half":', encoding="utf-8")
    assert checkpoint.load(context, identity, 1) is None
    checkpoint.invalidate()
    assert checkpoint.load(context, identity, 1) is None
    checkpoint.invalidate()

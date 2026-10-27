"""未验证的 CLI 版本继续被拒绝，但错误必须说清当前版本、已验证列表和下一步。"""

import asyncio
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext
from backend.providers.claude_agent.runtime import VERIFIED_COMPACTION_CONTROL
from tests.test_claude_runtime import CompactionClient, runtime


@pytest.mark.asyncio
async def test_unverified_cli_version_is_rejected_with_actionable_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = CompactionClient([])
    adapter = runtime(tmp_path, monkeypatch, client)
    adapter.identity = replace(adapter.identity, cli_version="2.1.302", sdk_version="0.2.163")
    adapter.config = replace(
        adapter.config, disable_auto_compaction=True, identity=adapter.identity
    )
    result = await adapter.execute(
        RunContext(uuid4()), "京都", None, lambda e: None, asyncio.Event()
    )
    assert (result.code, result.reason) == ("blocked", "auto_compaction_capability")
    assert not client.queried.is_set()
    assert "2.1.302" in result.text and "不在已验证列表" in result.text
    assert all(cli in result.text for _, cli in VERIFIED_COMPACTION_CONTROL)
    assert "claude-code@2.1.295" in result.text and "dev.py doctor" in result.text

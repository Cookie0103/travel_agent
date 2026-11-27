"""本机模型线路走普通请求守卫，使用独立的零元账本。"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext
from backend.limits import LOCAL_MODEL, ProbeError
from backend.providers.claude_agent.live import run_live, runtime_budget
from backend.providers.claude_agent.request import validate_request
from backend.providers.claude_agent.settings import load_runtime_settings


def test_local_sdk_uses_pinned_model_zero_ledger_and_production_fence(tmp_path: Path) -> None:
    settings = load_runtime_settings({}, local_evaluation=True)
    assert settings.provider == "ollama" and settings.model == LOCAL_MODEL
    guarded = validate_request(
        json.dumps(
            {"model": LOCAL_MODEL, "max_tokens": 10, "messages": [], "stream": True}
        ).encode(),
        LOCAL_MODEL,
        frozenset(),
    )
    assert guarded.charge == Decimal(0)
    ledger = runtime_budget(tmp_path, settings, phase2=True)
    request = ledger.reserve(guarded.charge, datetime.now(UTC))
    ledger.settle(request, Decimal(0))
    assert ledger.totals() == (1, Decimal(0))
    assert ledger.path.name == "phase2-ollama.jsonl"
    assert not ledger.path.with_name("phase2-deepseek.jsonl").exists()
    with pytest.raises(ProbeError, match="专用本地库"):
        run_live(
            "离线配置验收",
            RunContext(uuid4()),
            tmp_path,
            provider="ollama",
            evaluation={"suite": "v3"},
            database_dsn="postgresql://localhost/travel_agent",
        )

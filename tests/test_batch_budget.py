"""本批明确授权的费用边界：新日期生效、HUMAN 不绕过、重启不重置。"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from backend.limits import ProbeError
from backend.providers.claude_agent.budget import GRANT, Budget, Entry
from backend.providers.claude_agent.ledger import Entry as LegacyEntry
from backend.providers.claude_agent.ledger import Ledger

START = datetime(2026, 10, 13, tzinfo=UTC)


@pytest.mark.parametrize("profile", ["default", "human"])
def test_batch_daily_authorization_allows_sixty_but_not_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    monkeypatch.setenv("TRAVEL_PROFILE", profile)
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(100))
    assert budget.daily_limit(START) == Decimal(60)
    budget.reserve(Decimal(60), START)
    with pytest.raises(ProbeError, match="今日"):
        Budget(budget.path, budget.legacy, Decimal(100)).reserve(Decimal("0.01"), START)
    assert budget.totals() == (1, Decimal(60))


def test_batch_total_survives_restart_days_and_conservatively_counts_reservations(
    tmp_path: Path,
) -> None:
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(60))
    budget.append(Entry(GRANT, "old", "attempt", "2026-10-12", "1000", "CNY"))
    for offset in range(3):
        budget.reserve(Decimal(50), START + timedelta(days=offset))
    restored = Budget(budget.path, budget.legacy, Decimal(60))
    before = budget.path.read_bytes()
    with pytest.raises(ProbeError, match="累计"):
        restored.reserve(Decimal("0.01"), START + timedelta(days=3))
    assert budget.path.read_bytes() == before
    assert restored.totals() == (4, Decimal(1150))


def test_batch_settlement_releases_unused_batch_reservation(tmp_path: Path) -> None:
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(60))
    for offset in range(2):
        budget.reserve(Decimal(60), START + timedelta(days=offset))
    pending = budget.reserve(Decimal(30), START + timedelta(days=2))
    budget.settle(pending, Decimal(1))
    budget.reserve(Decimal(29), START + timedelta(days=2))
    with pytest.raises(ProbeError, match="累计"):
        budget.reserve(Decimal("0.01"), START + timedelta(days=3))


def test_batch_counts_old_ledger_calls_since_batch_start(tmp_path: Path) -> None:
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(60))
    Ledger(budget.legacy).append(LegacyEntry("attempt", "2026-10-13", "CNY", "60"))
    budget.reserve(Decimal(60), START + timedelta(days=1))
    budget.reserve(Decimal(30), START + timedelta(days=2))
    with pytest.raises(ProbeError, match="累计"):
        budget.reserve(Decimal("0.01"), START + timedelta(days=3))


@pytest.mark.parametrize("amount", [Decimal(0), Decimal("NaN")])
def test_batch_human_cannot_bypass_disabled_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, amount: Decimal
) -> None:
    monkeypatch.setenv("TRAVEL_PROFILE", "human")
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", amount)
    with pytest.raises(ProbeError):
        budget.reserve(Decimal(1), START)
    assert not budget.path.exists()

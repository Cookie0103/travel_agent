"""SDK 费用失败路径：新授权、UTC 当日、旧账本和崩溃占用不可混淆。"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from backend.providers.probe.ledger import Entry, Ledger
from backend.providers.probe.settings import ProbeError
from backend.providers.sdk_probe.budget import Budget

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


def test_old_spend_counts_for_daily_but_not_new_grant(tmp_path: Path) -> None:
    old = tmp_path / "old.jsonl"
    Ledger(old).append(Entry("attempt", "2026-10-03", "CNY", "0.10"))
    budget = Budget(tmp_path / "new.jsonl", old, Decimal("0.15"))
    budget.reserve(Decimal("0.04"), NOW)
    with pytest.raises(ProbeError, match="今日"):
        budget.reserve(Decimal("0.02"), NOW)
    assert budget.totals() == (1, Decimal("0.04"))


def test_restart_and_next_day_do_not_reset_total_authorization(tmp_path: Path) -> None:
    path = tmp_path / "new.jsonl"
    Budget(path, tmp_path / "old", Decimal(5)).reserve(Decimal(3), NOW)
    resumed = Budget(path, tmp_path / "old", Decimal(5))
    with pytest.raises(ProbeError, match="累计"):
        resumed.reserve(Decimal(3), NOW + timedelta(days=1))
    assert resumed.totals() == (1, Decimal(3))


def test_request_limit_is_not_model_turn_limit(tmp_path: Path) -> None:
    budget = Budget(tmp_path / "new.jsonl", tmp_path / "old", Decimal(5))
    for _ in range(100):
        budget.reserve(Decimal("0.001"), NOW)
    with pytest.raises(ProbeError, match="累计"):
        budget.reserve(Decimal("0.001"), NOW)


@pytest.mark.parametrize("content", ["{", '{"charge_cny":"0"}', "\ufffd"])
def test_corrupt_ledger_refuses_to_reset(tmp_path: Path, content: str) -> None:
    path = tmp_path / "new.jsonl"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ProbeError, match="损坏"):
        Budget(path, tmp_path / "old", Decimal(5)).reserve(Decimal(1), NOW)
    assert path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("limit", [Decimal(0), Decimal(-1), Decimal("NaN")])
def test_invalid_daily_budget_never_reserves(tmp_path: Path, limit: Decimal) -> None:
    budget = Budget(tmp_path / "new.jsonl", tmp_path / "old", limit)
    with pytest.raises(ProbeError):
        budget.reserve(Decimal("0.01"), NOW)
    assert not budget.path.exists()


def test_settlement_releases_only_unused_money_not_request_count(tmp_path: Path) -> None:
    budget = Budget(tmp_path / "new", tmp_path / "old", Decimal(5))
    request_id = budget.reserve(Decimal("2.12"), NOW)
    budget.settle(request_id, Decimal("0.002"))
    assert Budget(budget.path, budget.legacy, budget.daily).totals() == (1, Decimal("0.002"))
    with pytest.raises(ProbeError):
        budget.settle(request_id, Decimal("0.001"))


@pytest.mark.parametrize("amount", [Decimal("3"), Decimal("-1"), Decimal("NaN")])
def test_invalid_settlement_keeps_full_reservation(tmp_path: Path, amount: Decimal) -> None:
    budget = Budget(tmp_path / "new", tmp_path / "old", Decimal(5))
    request_id = budget.reserve(Decimal("2.12"), NOW)
    with pytest.raises(ProbeError):
        budget.settle(request_id, amount)
    assert budget.totals() == (1, Decimal("2.12"))

"""SDK 费用失败路径：新授权、UTC 当日、旧账本和崩溃占用不可混淆。"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from backend.providers.claude_agent.budget import LIMITS, Budget
from backend.providers.claude_agent.ledger import Entry, Ledger
from backend.providers.claude_agent.limits import Currency, ProbeError

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


@pytest.fixture
def bounded_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    """原有限授权仍受保护；用户新授权不使有限上限实现失效。"""
    monkeypatch.setitem(LIMITS, "CNY", (Decimal(5), 100))


def test_old_spend_counts_for_daily_but_not_new_grant(tmp_path: Path) -> None:
    old = tmp_path / "old.jsonl"
    Ledger(old).append(Entry("attempt", "2026-10-03", "CNY", "0.10"))
    budget = Budget(tmp_path / "new.jsonl", old, Decimal("0.15"))
    budget.reserve(Decimal("0.04"), NOW)
    with pytest.raises(ProbeError, match="今日"):
        budget.reserve(Decimal("0.02"), NOW)
    assert budget.totals() == (1, Decimal("0.04"))


def test_restart_and_next_day_do_not_reset_total_authorization(
    tmp_path: Path,
    bounded_grant: None,
) -> None:
    path = tmp_path / "new.jsonl"
    Budget(path, tmp_path / "old", Decimal(5)).reserve(Decimal(3), NOW)
    resumed = Budget(path, tmp_path / "old", Decimal(5))
    with pytest.raises(ProbeError, match="累计"):
        resumed.reserve(Decimal(3), NOW + timedelta(days=1))
    assert resumed.totals() == (1, Decimal(3))


def test_request_limit_is_not_model_turn_limit(tmp_path: Path, bounded_grant: None) -> None:
    budget = Budget(tmp_path / "new.jsonl", tmp_path / "old", Decimal(5))
    for _ in range(100):
        budget.reserve(Decimal("0.001"), NOW)
    with pytest.raises(ProbeError, match="累计"):
        budget.reserve(Decimal("0.001"), NOW)


def test_full_test_repeats_rejected_before_any_budget_reservation(
    tmp_path: Path,
    bounded_grant: None,
) -> None:
    budget = Budget(tmp_path / "new.jsonl", tmp_path / "old", Decimal(5))
    with pytest.raises(ProbeError, match="不足完整评测"):
        budget.check_minimum_requests(40 * 3)
    assert not budget.path.exists()
    budget.check_minimum_requests(100)
    budget.reserve(Decimal("0.001"), NOW)
    with pytest.raises(ProbeError, match="不足完整评测"):
        budget.check_minimum_requests(100)
    assert budget.totals() == (1, Decimal("0.001"))


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


def test_daily_only_grant_preserves_history_and_allows_more_than_old_request_cap(
    tmp_path: Path,
) -> None:
    path, legacy = tmp_path / "current", tmp_path / "legacy"
    budget = Budget(path, legacy, Decimal(15))
    for _ in range(101):
        request_id = budget.reserve(Decimal("0.001"), NOW)
        budget.settle(request_id, Decimal("0.001"))
    before = path.read_bytes()
    resumed = Budget(path, legacy, Decimal(15))
    resumed.check_minimum_requests(120)
    assert resumed.totals() == (101, Decimal("0.101")) and path.read_bytes() == before
    resumed.reserve(Decimal(6), NOW + timedelta(days=1))
    assert resumed.totals() == (102, Decimal("6.101"))


def test_human_daily_ceiling_cannot_be_raised_by_configuration_or_restart(tmp_path: Path) -> None:
    path, legacy = tmp_path / "current", tmp_path / "legacy"
    Ledger(legacy).append(Entry("attempt", "2026-10-03", "CNY", "0.10"))
    budget = Budget(path, legacy, Decimal(100))
    request_id = budget.reserve(Decimal("14.80"), NOW)
    before = path.read_bytes()
    with pytest.raises(ProbeError, match="今日"):
        Budget(path, legacy, Decimal(100)).reserve(Decimal("0.11"), NOW)
    assert path.read_bytes() == before
    budget.settle(request_id, Decimal("14.80"))
    budget.reserve(Decimal("0.10"), NOW)
    with pytest.raises(ProbeError, match="今日"):
        budget.reserve(Decimal("0.001"), NOW)
    budget.reserve(Decimal(15), NOW + timedelta(days=1))
    assert budget.totals() == (3, Decimal("29.90"))


def test_lower_configured_budget_and_usd_zero_grant_are_preserved(tmp_path: Path) -> None:
    budget = Budget(tmp_path / "current", tmp_path / "legacy", Decimal(1))
    with pytest.raises(ProbeError, match="今日"):
        budget.reserve(Decimal("1.01"), NOW)
    usd = Budget(tmp_path / "usd", tmp_path / "legacy", Decimal(100), "USD")
    with pytest.raises(ProbeError, match="美元"):
        usd.reserve(Decimal("0.01"), NOW)
    assert not budget.path.exists() and not usd.path.exists()


def test_today_exception_retains_ledger_and_expires_at_utc_midnight(tmp_path: Path) -> None:
    """用户今日追加授权不重置账本，也不能通过重启延长到明天。"""
    path, legacy = tmp_path / "current", tmp_path / "legacy"
    today = NOW + timedelta(days=1)
    budget = Budget(path, legacy, Decimal(15))
    first = budget.reserve(Decimal(16), today)
    budget.settle(first, Decimal(16))
    before = path.read_bytes()
    resumed = Budget(path, legacy, Decimal(15))
    assert resumed.daily_limit(today) is None
    resumed.reserve(Decimal(16), today)
    assert path.read_bytes().startswith(before)
    assert resumed.totals() == (2, Decimal(32))
    tomorrow = today + timedelta(days=1)
    assert resumed.daily_limit(tomorrow) == Decimal(15)
    with pytest.raises(ProbeError, match="今日"):
        resumed.reserve(Decimal("15.01"), tomorrow)
    assert resumed.totals() == (2, Decimal(32))


@pytest.mark.parametrize("currency", ["CNY", "USD"])
def test_today_exception_keeps_disabled_budget_and_usd_blocked(
    tmp_path: Path, currency: Currency
) -> None:
    today = NOW + timedelta(days=1)
    budget = Budget(tmp_path / currency, tmp_path / "legacy", Decimal(0), currency)
    with pytest.raises(ProbeError):
        budget.reserve(Decimal(1), today)
    assert not budget.path.exists()


def test_today_exception_uses_utc_day_and_preserves_lower_limits_afterward(tmp_path: Path) -> None:
    budget = Budget(tmp_path / "current", tmp_path / "legacy", Decimal(1))
    local_midnight = datetime.fromisoformat("2026-10-05T00:00:00+09:00")
    assert budget.daily_limit(local_midnight) is None
    assert budget.daily_limit(datetime(2026, 10, 5, tzinfo=UTC)) == Decimal(1)

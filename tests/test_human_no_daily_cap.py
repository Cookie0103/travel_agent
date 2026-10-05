"""HUMAN档不施加每日CNY上限；default/relaxed保持15 CNY；USD始终阻断。"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from backend import server
from backend.providers.claude_agent.budget import GRANT, Budget, Entry
from backend.providers.claude_agent.limits import Currency, ProbeError
from backend.providers.claude_agent.profile import DEFAULT, HUMAN, RELAXED

NOW = datetime(2026, 10, 5, 1, tzinfo=UTC)


def overspent(tmp_path: Path, daily: Decimal = Decimal(15)) -> Budget:
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", daily)
    budget.append(Entry(GRANT, "old", "attempt", "2026-10-05", "15.5", "CNY"))
    return budget


def test_human_reserves_past_15_and_still_writes_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TRAVEL_PROFILE", "human")
    monkeypatch.setattr("backend.trace_log._stdout", True)
    budget = overspent(tmp_path)
    request_id = budget.reserve(Decimal("0.2"), NOW, "abcdef01")
    budget.settle(request_id, Decimal("0.1"))
    assert budget.totals() == (2, Decimal("15.6"))
    assert [e.kind for e in budget.entries()] == ["attempt", "attempt", "settled"]
    (record,) = [json.loads(x.removeprefix("TRACE ")) for x in capsys.readouterr().out.splitlines()]
    assert record["ev"] == "budget_reserved" and record["daily_limit"] is None
    assert record["daily_cap"] is False


@pytest.mark.parametrize("profile", ["", "relaxed"])
def test_default_and_relaxed_still_block_past_15(
    profile: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRAVEL_PROFILE", profile)
    budget = overspent(tmp_path)
    with pytest.raises(ProbeError, match="今日原币种余额不足"):
        budget.reserve(Decimal("0.2"), NOW)
    assert budget.totals() == (1, Decimal("15.5"))


@pytest.mark.parametrize("profile", ["", "relaxed"])
@pytest.mark.parametrize("daily", [Decimal(0), Decimal("NaN"), Decimal(-1)])
def test_invalid_daily_budget_fails_closed_outside_human(
    profile: str, daily: Decimal, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRAVEL_PROFILE", profile)
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", daily)
    with pytest.raises(ProbeError):
        budget.reserve(Decimal(1), NOW)
    assert not budget.path.exists()


def test_invalid_daily_budget_is_ignored_under_human(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRAVEL_PROFILE", "human")
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(0))
    budget.reserve(Decimal(1), NOW)
    assert budget.totals() == (1, Decimal(1))
    with pytest.raises(ProbeError):  # 单次预占本身仍须为正
        budget.reserve(Decimal(0), NOW)


@pytest.mark.parametrize("currency", ["CNY", "USD"])
def test_usd_stays_blocked_under_human(
    currency: Currency, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRAVEL_PROFILE", "human")
    budget = Budget(tmp_path / currency, tmp_path / "legacy", Decimal(15), currency)
    if currency == "USD":
        with pytest.raises(ProbeError, match="美元"):
            budget.reserve(Decimal(1), NOW)
        assert not budget.path.exists()
    else:
        assert budget.daily_limit(NOW) is None
        assert budget.reserve(Decimal(1), NOW)
    assert Budget(tmp_path / "u", tmp_path / "l", Decimal(15), "USD").daily_limit(NOW) == 15


def test_profile_flags_and_boot_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (DEFAULT.daily_cny_cap, RELAXED.daily_cny_cap, HUMAN.daily_cny_cap) == (
        True,
        True,
        False,
    )
    monkeypatch.setattr("backend.trace_log._stdout", True)
    for profile, expected in (("human", False), ("relaxed", True), ("", True)):
        monkeypatch.setenv("TRAVEL_PROFILE", profile)
        server.log_boot()
        record = json.loads(capsys.readouterr().out.strip().removeprefix("TRACE "))
        assert record["limits"]["daily_cap"] is expected

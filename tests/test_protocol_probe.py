"""离线验证 M0.2 的配置、持久次数限制、费用隔离和工具配对。"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from backend.providers.claude_agent.ledger import Entry, Ledger, exclusive
from backend.providers.claude_agent.limits import (
    ProbeError,
    Settings,
    load_settings,
    price_for,
    read_budget,
)

NOW = datetime(2026, 10, 3, tzinfo=UTC)
SETTINGS = Settings("fake-key-for-tests", "deepseek-flash", Decimal("5"), Decimal("0"))


@pytest.mark.parametrize("value", ["", "bad", "NaN", "Infinity", "-0.1"])
def test_invalid_budget_is_rejected_without_echoing_input(value: str) -> None:
    with pytest.raises(ProbeError, match="validation"):
        read_budget(value)


@pytest.mark.parametrize("model", ["", "deepseek-chat", "claude-sonnet", "unknown"])
def test_missing_or_unpriced_model_is_rejected(model: str) -> None:
    with pytest.raises(ProbeError, match="DEEPSEEK_MODEL"):
        load_settings(
            {
                "DEEPSEEK_API_KEY": "fake-secret",
                "DEEPSEEK_MODEL": model,
                "DAILY_BUDGET_CNY": "5",
                "DAILY_BUDGET_USD": "0",
            }
        )


def test_selected_model_changes_pricing_without_exposing_secret() -> None:
    settings = load_settings(
        {
            "DEEPSEEK_API_KEY": "fake-secret",
            "DEEPSEEK_MODEL": "deepseek-v4-pro",
            "DAILY_BUDGET_CNY": "5",
            "DAILY_BUDGET_USD": "0",
        }
    )
    assert settings.model == "deepseek-v4-pro"
    assert "fake-secret" not in repr(settings)
    assert price_for(settings.model).usage_upper(1000, 1000) == Decimal("0.036")
    assert price_for("deepseek-flash").usage_upper(1000, 1000) == Decimal("0.010")


def test_usd_budget_cannot_enable_disabled_deepseek() -> None:
    with pytest.raises(ProbeError, match="blocked"):
        load_settings(
            {
                "DEEPSEEK_API_KEY": "fake-key",
                "DEEPSEEK_MODEL": "deepseek-flash",
                "DAILY_BUDGET_CNY": "0",
                "DAILY_BUDGET_USD": "100",
            }
        )


def test_missing_key_is_rejected() -> None:
    with pytest.raises(ProbeError, match="API Key"):
        load_settings({})


def test_restart_and_new_day_do_not_reset_batch_request_count(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    for _ in range(4):
        Ledger(path).charge("CNY", Decimal("0.05"), Decimal("1"), NOW)
    with pytest.raises(ProbeError, match="四次"):
        Ledger(path).charge("CNY", Decimal("0.05"), Decimal("1"), NOW + timedelta(days=1))
    assert len(Ledger(path).entries()) == 4


def test_currency_budgets_cannot_borrow_from_each_other(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.charge("USD", Decimal("1"), Decimal("1"), NOW)
    ledger.charge("CNY", Decimal("0.05"), Decimal("0.05"), NOW)
    with pytest.raises(ProbeError, match="预算不足"):
        ledger.charge("CNY", Decimal("0.05"), Decimal("0.05"), NOW)
    assert len(ledger.entries()) == 2


def test_success_or_two_flows_prevents_paid_repetition(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.start_flow(NOW)
    ledger.start_flow(NOW)
    with pytest.raises(ProbeError, match="两次"):
        ledger.start_flow(NOW)
    ledger.append(Entry("success", "2026-10-03", "CNY"))
    with pytest.raises(ProbeError, match="已成功"):
        ledger.start_flow(NOW)


def test_corrupt_ledger_blocks_instead_of_resetting(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"partial":', encoding="utf-8")
    with pytest.raises(ProbeError, match="损坏"):
        Ledger(path).charge("CNY", Decimal("0.05"), Decimal("5"), NOW)
    assert path.read_text(encoding="utf-8") == '{"partial":'


def test_concurrent_flow_lock_blocks_second_run_and_releases_after_error(tmp_path: Path) -> None:
    path = tmp_path / "running.lock"
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        with exclusive(path):
            with pytest.raises(ProbeError, match="正在运行"):
                with exclusive(path):
                    pytest.fail("concurrent lock was acquired")
            raise RuntimeError("synthetic interruption")
    assert not path.exists()

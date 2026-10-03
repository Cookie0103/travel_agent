"""离线验证 M0.2 的配置、持久次数限制、费用隔离和工具配对。"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from anthropic.types import Message, MessageParam, ToolParam

from backend.providers.probe.flow import execute_flow, synthetic_results, write_report
from backend.providers.probe.ledger import Entry, Ledger, exclusive
from backend.providers.probe.settings import (
    ProbeError,
    Settings,
    load_settings,
    price_for,
    read_budget,
)
from backend.providers.probe.transport import Reply

NOW = datetime(2026, 10, 3, tzinfo=UTC)
SETTINGS = Settings("fake-key-for-tests", "deepseek-flash", Decimal("5"), Decimal("0"))


def reply(content: list[dict[str, object]], stop: str = "tool_use") -> Reply:
    return Reply(
        Message.model_validate(
            {
                "id": "offline-message",
                "type": "message",
                "role": "assistant",
                "model": "deepseek-flash",
                "content": content,
                "stop_reason": stop,
                "stop_sequence": None,
                "usage": {"input_tokens": 12, "output_tokens": 8},
            }
        ),
        ("message_start", "content_block_delta", "message_stop"),
    )


def tool(call_id: str, city: str = "Kyoto") -> dict[str, object]:
    return {"type": "tool_use", "id": call_id, "name": "lookup_fixture", "input": {"city": city}}


class FakeClient:
    """脚本化结果，无 HTTP；保留内存请求用于断言续接内容。"""

    def __init__(self, replies: list[Reply]) -> None:
        self.replies = iter(replies)
        self.calls: list[list[MessageParam]] = []

    def send(self, messages: list[MessageParam], tools: list[ToolParam]) -> Reply:
        self.calls.append(list(messages))
        return next(self.replies)


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


def test_roundtrip_preserves_thinking_and_pairs_reordered_results(tmp_path: Path) -> None:
    """R02：工具结果以 ID 配对，SDK 思考块内存原样回传但不写报告。"""
    thinking: dict[str, object] = {
        "type": "thinking",
        "thinking": "private-test-thought",
        "signature": "test-signature",
    }
    first = reply([thinking, tool("call-a"), tool("call-b", "Osaka")])
    client = FakeClient(
        [first, reply([{"type": "text", "text": "fixture ok; Osaka unavailable"}], "end_turn")]
    )
    path = tmp_path / "report.json"
    report = execute_flow(SETTINGS, client.send, lambda item: write_report(path, item))
    assert report["status"] == "success"
    assert report["tool_count"] == 2
    assert report["is_error_true_sent"] is True
    assert client.calls[1][1]["content"] == first.message.content
    results = synthetic_results(first)
    assert [result["tool_use_id"] for result in results] == ["call-b", "call-a"]
    assert results[0]["is_error"] is True
    assert "private-test-thought" not in path.read_text(encoding="utf-8")
    assert "test-signature" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "content",
    [
        [tool("same"), tool("same")],
        [tool("a", "Tokyo")],
        [{"type": "tool_use", "id": "a", "name": "other", "input": {}}],
    ],
)
def test_invalid_tool_response_prevents_second_request(content: list[dict[str, object]]) -> None:
    """R02：重复 ID、未知工具和非法参数都不能成为下一轮输入。"""
    client = FakeClient([reply(content)])
    reports: list[dict[str, object]] = []
    with pytest.raises(ProbeError, match="validation"):
        execute_flow(SETTINGS, client.send, lambda item: reports.append(dict(item)))
    assert len(client.calls) == 1
    assert reports[-1]["status"] == "failed"


def test_truncated_final_answer_fails_without_third_request() -> None:
    client = FakeClient(
        [reply([tool("a")]), reply([{"type": "text", "text": "partial"}], "max_tokens")]
    )
    with pytest.raises(ProbeError, match="完整最终回答"):
        execute_flow(SETTINGS, client.send, lambda item: None)
    assert len(client.calls) == 2


def test_report_overwrite_keeps_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    write_report(path, {"status": "running"})
    write_report(path, {"status": "failed"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"status": "failed"}

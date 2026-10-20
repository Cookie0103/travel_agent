"""模型 HTTP 重试只在流开始前；未知用量保留预占。"""

import json
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from backend.limits import ProbeError, Settings, StallError
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.guard import Guard
from tests.model_bodies import request_body, response_body


@pytest.mark.parametrize("status", [429, 503, 529])
def test_http_failure_retries_once_and_keeps_unknown_charge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    ledger = tmp_path / "ledger"
    budget = Budget(ledger, tmp_path / "legacy", Decimal(5))
    calls = 0

    def forward(_: bytes) -> tuple[int, bytes]:
        nonlocal calls
        calls += 1
        return (status, b"private response") if calls == 1 else (200, response_body())

    guard = Guard(Settings("private", "deepseek-flash", Decimal(5), Decimal(0)), budget, forward)
    assert guard.accept("/v1/messages", "Bearer " + guard.token, request_body())[0] == 200
    assert calls == guard.attempts == 2 and guard.failures == []
    assert guard.http_retries == 1 and guard.upstream_status is None
    assert (
        len(
            [
                line
                for line in ledger.read_text(encoding="utf-8").splitlines()
                if json.loads(line)["kind"] == "settled"
            ]
        )
        == 1
    )


def test_two_failures_end_with_safe_provider_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(5))
    guard = Guard(
        Settings("private", "deepseek-flash", Decimal(5), Decimal(0)),
        budget,
        lambda _: (503, b"private body"),
    )
    status, body = guard.accept("/v1/messages", "Bearer " + guard.token, request_body())
    assert status == 400 and b"provider_error" in body and b"private" not in body
    assert guard.attempts == 2 and guard.http_retries == 1 and guard.upstream_status == 503


@pytest.mark.parametrize("first", ["http", "stall"])
def test_http_and_stall_retries_do_not_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first: str
) -> None:
    monkeypatch.setenv("TRAVEL_PROFILE", "human")
    monkeypatch.setattr(time, "sleep", lambda _: None)
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(5))
    calls = 0

    def forward(_: bytes) -> tuple[int, bytes]:
        nonlocal calls
        calls += 1
        if (calls == 1) == (first == "stall"):
            raise StallError("child_connecting", 26)
        return 429, b"private body"

    guard = Guard(Settings("private", "deepseek-flash", Decimal(5), Decimal(0)), budget, forward)
    assert guard.accept("/v1/messages", "Bearer " + guard.token, request_body())[0] == 400
    assert calls == 2


def test_partial_200_stream_is_never_replayed(tmp_path: Path) -> None:
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(5))
    guard = Guard(
        Settings("private", "deepseek-flash", Decimal(5), Decimal(0)),
        budget,
        lambda _: (200, b"data: {}\n\n"),
    )
    assert guard.accept("/v1/messages", "Bearer " + guard.token, request_body())[0] == 400
    assert guard.attempts == 1


def test_budget_rejects_retry_without_claiming_second_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    budget = Budget(tmp_path / "ledger", tmp_path / "legacy", Decimal(5))
    original = budget.reserve
    reservations = 0

    def reserve(amount: Decimal, now: datetime, run: object = None) -> str:
        nonlocal reservations
        reservations += 1
        if reservations == 2:
            raise ProbeError("blocked", "预算不足")
        return original(amount, now, run)

    monkeypatch.setattr(budget, "reserve", reserve)
    guard = Guard(
        Settings("private", "deepseek-flash", Decimal(5), Decimal(0)),
        budget,
        lambda _: (429, b"private"),
    )
    assert guard.accept("/v1/messages", "Bearer " + guard.token, request_body())[0] == 400
    assert guard.attempts == 1 and guard.http_retries == guard.last_http_retries == 0
    assert budget.totals()[0] == 1

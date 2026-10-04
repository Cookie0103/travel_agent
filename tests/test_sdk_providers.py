"""R17供应商选择、原币种账本及离线Messages契约；从不使用真实密钥。"""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from backend.domain.execution import RunContext
from backend.providers.claude_agent.budget import GRANT, Budget
from backend.providers.claude_agent.guard import Guard
from backend.providers.claude_agent.http import _direct_request
from backend.providers.claude_agent.limits import ProbeError, Provider, Settings, price_for
from backend.providers.claude_agent.live import run_live
from backend.providers.claude_agent.request import validate_request
from backend.providers.claude_agent.response import summarize
from backend.providers.claude_agent.settings import load_runtime_settings
from tests.test_sdk_guard import request_body, response_body

MODEL = "claude-haiku-4-5-20251001"
NOW = datetime(2026, 10, 3, tzinfo=UTC)
ENV = {
    "LLM_PROVIDER": "anthropic",
    "ANTHROPIC_API_KEY": "synthetic-secret",
    "ANTHROPIC_MODEL": MODEL,
    "DAILY_BUDGET_CNY": "5",
    "DAILY_BUDGET_USD": "10",
}


def test_provider_is_explicit_and_keys_do_not_select_or_fallback() -> None:
    config = {**ENV, "DEEPSEEK_API_KEY": "other-secret", "DEEPSEEK_MODEL": "deepseek-flash"}
    usd = load_runtime_settings(config)
    assert (usd.provider, usd.currency, usd.daily_limit, usd.model) == (
        "anthropic",
        "USD",
        Decimal(10),
        MODEL,
    )
    del config["LLM_PROVIDER"]
    cny = load_runtime_settings(config)
    assert (cny.provider, cny.currency, cny.daily_limit) == ("deepseek", "CNY", Decimal(5))
    assert "secret" not in repr(usd) and "secret" not in repr(cny)
    del config["DEEPSEEK_API_KEY"]
    with pytest.raises(ProbeError, match="DeepSeek API Key"):
        load_runtime_settings(config)


@pytest.mark.parametrize(
    "changes",
    [
        {"LLM_PROVIDER": "openai"},
        {"LLM_PROVIDER": ""},
        {"ANTHROPIC_API_KEY": ""},
        {"ANTHROPIC_MODEL": "deepseek-flash"},
        {"ANTHROPIC_MODEL": "claude-sonnet-5-5"},
        {"DAILY_BUDGET_USD": "0"},
        {"DAILY_BUDGET_USD": "NaN"},
        {"DAILY_BUDGET_USD": "-1"},
    ],
)
def test_invalid_or_unverified_provider_config_is_rejected(changes: dict[str, str]) -> None:
    with pytest.raises(ProbeError):
        load_runtime_settings({**ENV, **changes})


def test_usd_daily_budget_never_grants_requests_or_borrows_cny(tmp_path: Path) -> None:
    budget = Budget(tmp_path / "usd", tmp_path / "old", Decimal(10), "USD")
    guard = Guard(load_runtime_settings(ENV), budget, lambda _: pytest.fail("no authorization"))
    status, content = guard.accept(
        "/v1/messages", "Bearer " + guard.token, request_body(model=MODEL)
    )
    assert status == 400 and b"synthetic-secret" not in content
    assert guard.attempts == 0 and budget.totals() == (0, Decimal(0))
    assert not budget.path.exists()


def test_usd_live_is_blocked_before_cli_or_transmission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        "backend.providers.claude_agent.live.find_cli", lambda _: pytest.fail("must not start SDK")
    )
    with pytest.raises(ProbeError, match="授权均为0"):
        run_live("离线", RunContext(uuid4()), tmp_path)
    assert not (tmp_path / ".cache").exists()


def test_legacy_cny_records_keep_bytes_count_and_settlement_semantics(tmp_path: Path) -> None:
    path = tmp_path / "deepseek"
    legacy = [
        {
            "grant": GRANT,
            "request_id": "old",
            "kind": "attempt",
            "day": "2026-10-03",
            "charge_cny": "2.1",
        },
        {
            "grant": GRANT,
            "request_id": "old",
            "kind": "settled",
            "day": "2026-10-03",
            "charge_cny": "0.03",
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in legacy), encoding="utf-8")
    before = path.read_bytes()
    budget = Budget(path, tmp_path / "old", Decimal(5))
    assert budget.totals() == (1, Decimal("0.03"))
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(before).digest()
    with pytest.raises(ProbeError, match="损坏"):
        Budget(path, tmp_path / "old", Decimal(10), "USD").totals()
    assert path.read_bytes() == before
    current = budget.reserve(Decimal("0.1"), NOW)
    budget.settle(current, Decimal("0.01"))
    assert Budget(path, budget.legacy, budget.daily).totals() == (2, Decimal("0.04"))
    assert path.read_bytes().startswith(before)


def test_mismatched_model_budget_currency_never_forwards(tmp_path: Path) -> None:
    guard = Guard(
        Settings("secret", MODEL, Decimal(5), Decimal(10)),
        Budget(tmp_path / "cny", tmp_path / "old", Decimal(5)),
        lambda _: pytest.fail("currency mismatch"),
    )
    assert (
        guard.accept("/v1/messages", "Bearer " + guard.token, request_body(model=MODEL))[0] == 400
    )
    assert guard.budget.totals() == (0, Decimal(0))


def test_claude_cache_write_is_bounded_at_one_hour_rate_and_reported_in_usd() -> None:
    request = validate_request(request_body(model=MODEL), MODEL)
    assert request.charge == Decimal("0.40512")
    content = response_body(
        model=MODEL,
        usage={
            "input_tokens": 100,
            "cache_creation_input_tokens": 500,
            "cache_read_input_tokens": 200,
            "output_tokens": 0,
        },
    )
    observation = summarize(content, request, MODEL, "USD")
    assert observation["usage_cost_upper"] == "0.0014"
    assert observation["currency"] == "USD" and "usage_cost_upper_cny" not in observation
    assert "reserved_cny" not in observation
    assert price_for(MODEL).currency == "USD"
    for invalid in (
        b"data: {}\n\n",
        response_body(model=MODEL, usage={}),
        response_body(model=MODEL, usage={"input_tokens": 200001, "output_tokens": 0}),
    ):
        with pytest.raises(ProbeError):
            summarize(invalid, request, MODEL, "USD")
    with pytest.raises(ProbeError, match="币种"):
        summarize(content, request, MODEL, "CNY")


@pytest.mark.parametrize(
    "provider,host,path,auth",
    [
        (
            "deepseek",
            "api.deepseek.com",
            "/anthropic/v1/messages",
            {"Authorization": "Bearer synthetic"},
        ),
        ("anthropic", "api.anthropic.com", "/v1/messages", {"x-api-key": "synthetic"}),
    ],
)
def test_https_transport_only_uses_fixed_host_path_and_auth(
    monkeypatch: pytest.MonkeyPatch, provider: str, host: str, path: str, auth: dict[str, str]
) -> None:
    calls: list[object] = []

    class Response:
        status = 200

        def read(self, limit: int) -> bytes:
            assert limit == 1048577
            return b"synthetic response"

    class Connection:
        def __init__(self, hostname: str, timeout: int) -> None:
            assert (hostname, timeout) == (host, 45)

        def request(self, method: str, url: str, body: bytes, headers: dict[str, str]) -> None:
            assert (method, url, body) == ("POST", path, b"{}")
            assert headers == {
                **auth,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            }
            calls.append(method)

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            calls.append("closed")

    monkeypatch.setattr(
        "backend.providers.claude_agent.http.http.client.HTTPSConnection", Connection
    )
    assert _direct_request("synthetic", b"{}", TypeAdapter(Provider).validate_python(provider)) == (
        200,
        b"synthetic response",
    )
    assert calls == ["POST", "closed"]

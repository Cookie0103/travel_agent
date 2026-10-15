"""R17：授权网关与Haiku 5.5离线契约，不发真实模型请求。"""

import http.client as http_client
import json
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from backend.limits import ProbeError
from backend.providers.claude_agent import http
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.request import validate_request
from backend.providers.claude_agent.response import summarize
from backend.providers.claude_agent.settings import load_runtime_settings
from backend.services.models import model_options
from tests.test_sdk_guard import request_body, response_body

MODEL = "claude-haiku-5-5"
ENV = {
    "LLM_PROVIDER": "anthropic",
    "ANTHROPIC_API_KEY": "synthetic-private-key",
    "ANTHROPIC_MODEL": MODEL,
    "ANTHROPIC_BASE_URL": "https://api.teamorouter.com",
    "ANTHROPIC_LIVE_ENABLED": "1",
    "DAILY_BUDGET_USD": "10",
}


def test_authorized_haiku_gateway_is_selectable_without_network() -> None:
    option = model_options(ENV, True)[2]
    assert option.available and option.reason is None
    settings = load_runtime_settings(ENV)
    assert settings.model == MODEL and settings.daily_limit == Decimal(10)
    assert "private" not in repr(settings)
    for changes in ({"ANTHROPIC_LIVE_ENABLED": "0"}, {"DAILY_BUDGET_USD": "0"}):
        assert not model_options({**ENV, **changes}, True)[2].available


@pytest.mark.parametrize(
    "url",
    [
        "http://api.teamorouter.com",
        "https://api.teamorouter.com.evil.test",
        "https://api.teamorouter.com@evil.test",
        "https://api.teamorouter.com/v1",
        "https://api.teamorouter.com?key=private",
        "https://127.0.0.1",
        "https://api.teamorouter.com:444",
    ],
)
def test_unapproved_gateway_is_rejected_before_network(url: str) -> None:
    with pytest.raises(ProbeError) as captured:
        load_runtime_settings(
            {**ENV, "ANTHROPIC_MODEL": "claude-haiku-4-5-20251001", "ANTHROPIC_BASE_URL": url}
        )
    assert "private" not in str(captured.value)


@pytest.mark.parametrize(
    "provider,host,path,header",
    [
        ("anthropic", "api.teamorouter.com", "/v1/messages", "x-api-key"),
        ("deepseek", "api.deepseek.com", "/anthropic/v1/messages", "Authorization"),
    ],
)
def test_gateway_transport_preserves_protocol_and_deepseek_destination(
    monkeypatch: pytest.MonkeyPatch, provider: str, host: str, path: str, header: str
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", ENV["ANTHROPIC_BASE_URL"])
    sent: list[tuple[str, str, bytes, dict[str, str]]] = []
    closed: list[bool] = []

    class Response:
        status = 401

        def read(self, limit: int) -> bytes:
            return b"unauthorized"

    class Connection:
        def __init__(self, hostname: str, timeout: float) -> None:
            assert hostname == host

        def request(self, method: str, url: str, body: bytes, headers: dict[str, str]) -> None:
            sent.append((method, url, body, headers))

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(http_client, "HTTPSConnection", Connection)
    from pydantic import TypeAdapter

    from backend.limits import Provider

    assert http._direct_request(
        "synthetic", b"{}", TypeAdapter(Provider).validate_python(provider)
    ) == (
        401,
        b"unauthorized",
    )
    assert sent == [
        (
            "POST",
            path,
            b"{}",
            {
                header: "synthetic" if provider == "anthropic" else "Bearer synthetic",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
        )
    ]
    assert closed == [True]


def test_gateway_address_reaches_transport_child_without_key_in_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", ENV["ANTHROPIC_BASE_URL"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-private-key")
    monkeypatch.setenv("TRAVEL_PROFILE", "default")

    def forward(
        args: list[str], cwd: Path, env: dict[str, str], timeout: float, input_text: str
    ) -> subprocess.CompletedProcess[str]:
        assert env["ANTHROPIC_BASE_URL"] == "https://api.teamorouter.com"
        assert "ANTHROPIC_API_KEY" not in env
        assert "private-key" not in str(args) + str(env)
        assert json.loads(input_text)["key"] == "synthetic-private-key"
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"status": "ok", "http_status": 401, "content": "denied"})
        )

    monkeypatch.setattr(http, "run_process", forward)
    assert http.forward_messages("anthropic", "synthetic-private-key", b"{}") == (401, b"denied")


def test_haiku_defaults_keep_thinking_disabled_and_normalize_sampling() -> None:
    body = request_body(model=MODEL, temperature=1, top_p=0.99, output_config={"effort": "high"})
    normalized = json.loads(validate_request(body, MODEL).body)
    assert normalized["thinking"] == {"type": "disabled"}
    assert not {"temperature", "top_p", "top_k"}.intersection(normalized)
    assert normalized["output_config"] == {"effort": "high"}
    for changes in ({"temperature": 0}, {"top_k": 1}, {"output_config": {"effort": "max"}}):
        with pytest.raises(ProbeError):
            validate_request(request_body(model=MODEL, **changes), MODEL)


def test_haiku_cost_covers_long_context_and_one_hour_cache_write() -> None:
    request = validate_request(request_body(model=MODEL), MODEL)
    observation = summarize(
        response_body(
            model=MODEL,
            usage={
                "input_tokens": 100,
                "cache_creation_input_tokens": 500,
                "cache_read_input_tokens": 200,
                "output_tokens": 0,
            },
        ),
        request,
        MODEL,
        "USD",
    )
    # 100普通+500写缓存*2+200读缓存，均保守按0.50/百万；20输出按2.50/百万。
    assert observation["usage_cost_upper"] == "0.0007"
    assert observation["currency"] == "USD" and "usage_cost_upper_cny" not in observation
    with pytest.raises(ProbeError):
        summarize(response_body(model="different-model"), request, MODEL, "USD")


def test_enabled_usd_budget_persists_and_still_caps_human_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRAVEL_PROFILE", "human")
    now = datetime(2026, 10, 14, tzinfo=UTC)
    budget = Budget(tmp_path / "usd", tmp_path / "old", Decimal(10), "USD")
    request = budget.reserve(Decimal(9), now)
    budget.settle(request, Decimal(9))
    before = budget.path.read_bytes()
    resumed = Budget(budget.path, budget.legacy, Decimal(10), "USD")
    with pytest.raises(ProbeError, match="今日"):
        resumed.reserve(Decimal("1.01"), now)
    assert budget.path.read_bytes() == before
    resumed.reserve(Decimal(1), now)
    assert resumed.totals() == (2, Decimal(10))
    resumed.reserve(Decimal(10), now + timedelta(days=1))
    with pytest.raises(ProbeError):
        Budget(tmp_path / "disabled", budget.legacy, Decimal(0), "USD").reserve(Decimal(1), now)

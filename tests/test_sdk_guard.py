"""受控传输证明每次联网前计费、拒绝未知协议和无用量的半条响应。"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.guard import Guard
from backend.providers.claude_agent.limits import ProbeError, Settings
from backend.providers.claude_agent.request import TOOL_NAME, validate_request
from tests.test_sdk_cli_offline import scripted_response


def request_body(**changes: object) -> bytes:
    data = {
        "model": "deepseek-flash",
        "max_tokens": 1024,
        "stream": True,
        "tools": [{"name": TOOL_NAME, "input_schema": {"type": "object"}}],
        "messages": [{"role": "user", "content": "test"}],
    }
    data.update(changes)
    return json.dumps(data).encode()


def response_body(**changes: object) -> bytes:
    message: dict[str, object] = {
        "model": "deepseek-flash",
        "usage": {"input_tokens": 100, "output_tokens": 0},
    }
    message.update(changes)
    frames = [
        {"type": "message_start", "message": message},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 20},
        },
        {"type": "message_stop"},
    ]
    return b"".join(b"data: " + json.dumps(f).encode() + b"\n\n" for f in frames)


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "claude-sonnet-5"},
        {"max_tokens": 100000},
        {"max_tokens": True},
        {"stream": False},
        {"tools": [{"name": "Bash"}]},
        {"tools": []},
        {"messages": [{"role": "user", "content": [{"type": "image"}]}]},
        {"container": "server-execution"},
    ],
)
def test_guard_rejects_unbudgetable_request(changes: dict[str, object]) -> None:
    with pytest.raises(ProbeError):
        validate_request(request_body(**changes), "deepseek-flash")


def test_explicit_travel_tool_set_cannot_include_builtin_or_duplicate() -> None:
    names = frozenset({"mcp__travel__search_places", "mcp__travel__search_content"})
    valid = [{"name": name, "input_schema": {"type": "object"}} for name in names]
    assert validate_request(request_body(tools=valid), "deepseek-flash", names).charge > 0
    for invalid in ([valid[0], valid[0]], [valid[0], {"name": "Bash"}], [*valid, {"name": "Bash"}]):
        with pytest.raises(ProbeError):
            validate_request(request_body(tools=invalid), "deepseek-flash", names)


def test_network_failure_keeps_reservation_and_prevents_sdk_retry(tmp_path: Path) -> None:
    budget = Budget(tmp_path / "ledger", tmp_path / "old", Decimal(5))
    calls = 0

    def failing(body: bytes) -> tuple[int, bytes]:
        nonlocal calls
        calls += 1
        assert budget.totals()[0] == 1
        raise OSError("secret must not be exposed")

    guard = Guard(Settings("secret", "deepseek-flash", Decimal(5), Decimal(0)), budget, failing)
    for _ in range(2):
        status, content = guard.accept("/v1/messages", "Bearer " + guard.token, request_body())
        assert status == 400 and b"secret" not in content
    assert calls == 1 and budget.totals()[0] == 1


@pytest.mark.parametrize(
    "response", [response_body(model="other"), b"data: {}\n\n", response_body(usage={})]
)
def test_bad_upstream_stream_is_not_forwarded_as_success(tmp_path: Path, response: bytes) -> None:
    budget = Budget(tmp_path / "ledger", tmp_path / "old", Decimal(5))
    guard = Guard(
        Settings("secret", "deepseek-flash", Decimal(5), Decimal(0)),
        budget,
        lambda _: (200, response),
    )
    status, _ = guard.accept("/v1/messages", "Bearer " + guard.token, request_body())
    assert status == 400 and budget.totals()[0] == 1


def test_guard_forwards_success_and_caps_hidden_requests(tmp_path: Path) -> None:
    budget = Budget(tmp_path / "ledger", tmp_path / "old", Decimal(5))
    guard = Guard(
        Settings("secret", "deepseek-flash", Decimal(5), Decimal(0)),
        budget,
        lambda _: (200, response_body()),
        max_attempts=2,
    )
    statuses = [
        guard.accept("/v1/messages?beta=true", "Bearer " + guard.token, request_body())[0]
        for _ in range(3)
    ]
    assert statuses == [200, 200, 400]
    assert budget.totals()[0] == 2
    assert len(guard.observations) == 2


@pytest.mark.parametrize("allowed", [frozenset(), frozenset({TOOL_NAME})])
def test_forbidden_response_settles_once_and_blocks_followup(
    tmp_path: Path, allowed: frozenset[str]
) -> None:
    """R15：违规返回不能依赖 CLI 回调时序来阻止下一次付费请求。"""
    budget = Budget(tmp_path / "ledger", tmp_path / "old", Decimal(5))
    body = request_body(tools=[{"name": name} for name in allowed])
    guard = Guard(
        Settings("secret", "deepseek-flash", Decimal(5), Decimal(0)),
        budget,
        lambda data: scripted_response(data, tool_calls=(("Bash", {}),)),
        allowed_tools=allowed,
    )
    for _ in range(2):
        status, content = guard.accept("/v1/messages", "Bearer " + guard.token, body)
        assert status == 400 and b"Bash" not in content and b"secret" not in content
    assert guard.attempts == 1 and budget.totals()[0] == 1
    assert [entry.kind for entry in budget.entries()] == ["attempt", "settled"]
    assert budget.totals()[1] == Decimal(str(guard.observations[0]["usage_cost_upper"]))


@pytest.mark.parametrize("name", [None, "", 42])
def test_malformed_tool_name_keeps_reservation_and_stops_followup(
    tmp_path: Path, name: object
) -> None:
    budget = Budget(tmp_path / "ledger", tmp_path / "old", Decimal(5))
    body = request_body()
    status, content = scripted_response(body, tool_calls=((TOOL_NAME, {}),))
    malformed = content.replace(
        ('"name": ' + json.dumps(TOOL_NAME)).encode(),
        ('"name": ' + json.dumps(name)).encode(),
    )
    guard = Guard(
        Settings("secret", "deepseek-flash", Decimal(5), Decimal(0)),
        budget,
        lambda _: (status, malformed),
    )
    for _ in range(2):
        assert guard.accept("/v1/messages", "Bearer " + guard.token, body)[0] == 400
    assert guard.attempts == 1
    assert [entry.kind for entry in budget.entries()] == ["attempt"]
    assert budget.totals()[1] == validate_request(body, "deepseek-flash").charge


def test_local_endpoint_and_token_checked_before_reserving(tmp_path: Path) -> None:
    budget = Budget(tmp_path / "ledger", tmp_path / "old", Decimal(5))
    guard = Guard(
        Settings("secret", "deepseek-flash", Decimal(5), Decimal(0)),
        budget,
        lambda _: pytest.fail("must not forward"),
    )
    assert guard.accept("/v1/messages", "wrong-token", request_body())[0] == 400
    assert (
        guard.accept("/v1/messages/count_tokens", "Bearer " + guard.token, request_body())[0] == 400
    )
    assert budget.totals()[0] == 0

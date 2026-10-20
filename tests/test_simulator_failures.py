"""F11失败记录的UTF-8字节上限与凭据/身份脱敏。"""

import json
from uuid import uuid4

import pytest

from eval.simulator_failures import failure_details, private_output


def test_malformed_output_stays_available_without_secret_or_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "maps-private-test-value")
    raw = json.dumps(
        {
            "api_key": "maps-private-test-value",
            "text": f"a@example.com https://example.com/?key=value {uuid4()}",
        }
    )
    result = failure_details("invalid_simulator_output", raw, None)
    combined = str(result["raw_simulator_output"]) + str(result["rejected_action"])
    assert "maps-private-test-value" not in combined
    assert "a@example.com" not in combined and "https://example.com" not in combined
    assert '"api_key"' in combined and "[redacted]" in combined


def test_multibyte_output_is_bounded_and_valid_utf8_after_redaction() -> None:
    output = private_output("旅行🗾" * 1000)
    assert 2000 < len(output.encode("utf-8")) <= 2048
    assert output.encode("utf-8").decode("utf-8") == output
    details = failure_details("unknown_option", None, {"kind": "choice", "text": "旅行🗾" * 1000})
    assert details["raw_simulator_output"] is None
    rejected = details["rejected_action"]
    assert isinstance(rejected, str) and len(rejected.encode("utf-8")) <= 2048


def test_unavailable_simulator_does_not_copy_an_exception_message() -> None:
    result = failure_details("simulator_unavailable", None, None)
    assert result["reason"] == "simulator_unavailable"
    assert result["raw_simulator_output"] is result["rejected_action"] is None
    assert "password" not in json.dumps(result)


@pytest.mark.parametrize(
    "field",
    [
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "RAKUTEN_ACCESS_KEY",
        "oauth_token",
        "LANGFUSE_SECRET_KEY",
        "TRAVEL_TRACE_HMAC_KEY",
    ],
)
def test_credential_field_is_redacted_even_without_loaded_secret(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(field, raising=False)
    raw = json.dumps({field: "opaque-private-value"})
    assert "opaque-private-value" not in private_output(raw)
    assert "opaque-private-value" not in private_output(f"{field}=opaque-private-value")

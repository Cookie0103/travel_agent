"""模型菜单只验证配置，不需要数据库或真实请求。"""

import pytest

from backend.providers.claude_agent import budget
from backend.services.models import model_options, selected_provider
from backend.services.runs import MessageInput

ENVIRONMENT = {
    "DEEPSEEK_API_KEY": "private-test-key",
    "DEEPSEEK_MODEL": "deepseek-flash",
    "DAILY_BUDGET_CNY": "1",
    "ANTHROPIC_API_KEY": "private-anthropic-key",
    "ANTHROPIC_MODEL": "claude-haiku-4-5-20251001",
    "DAILY_BUDGET_USD": "1",
}


def test_models_are_available_only_with_enabled_and_valid_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(budget.LIMITS, "USD", (None, None))
    options = model_options(ENVIRONMENT, True)
    assert [item.id for item in options] == ["offline", "deepseek", "claude"]
    assert all(item.available for item in options)
    assert "private" not in str([item.model_dump() for item in options])
    assert selected_provider("deepseek") == "deepseek"
    assert selected_provider("claude") == "anthropic"


@pytest.mark.parametrize(
    "key", ["DEEPSEEK_API_KEY", "DAILY_BUDGET_CNY", "ANTHROPIC_API_KEY", "DAILY_BUDGET_USD"]
)
def test_missing_key_or_zero_budget_disables_only_that_model(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(budget.LIMITS, "USD", (None, None))
    env = {**ENVIRONMENT, key: "0" if "BUDGET" in key else ""}
    options = model_options(env, True)
    disabled = 1 if key in {"DEEPSEEK_API_KEY", "DAILY_BUDGET_CNY"} else 2
    assert not options[disabled].available and options[disabled].reason
    assert options[3 - disabled].available


def test_disabled_live_service_keeps_offline_available() -> None:
    options = model_options(ENVIRONMENT, False)
    assert options[0].available
    assert all(not item.available and item.reason == "服务未以 --live 启动" for item in options[1:])


@pytest.mark.parametrize("mode", ["offline", "deepseek", "claude"])
def test_message_accepts_each_selected_model(mode: str) -> None:
    message = MessageInput.model_validate(
        {
            "client_message_id": "00000000-0000-0000-0000-000000000001",
            "text": "大阪旅行",
            "mode": mode,
        }
    )
    assert message.mode == mode


def test_claude_unavailable_without_dollar_authorization_even_with_configuration() -> None:
    options = model_options(ENVIRONMENT, True)
    assert options[1].available
    assert not options[2].available
    assert options[2].reason and "授权" in options[2].reason

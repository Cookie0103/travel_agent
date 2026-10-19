"""E4：worker环境白名单最小化；供应商密钥只在需要实时数据的worker里出现。"""

from pathlib import Path

import pytest

from backend.providers.claude_agent.environment import worker_environment

SECRETS = {
    "GOOGLE_MAPS_API_KEY": "g-secret",
    "RAKUTEN_APP_ID": "r-app",
    "RAKUTEN_ACCESS_KEY": "r-access",
    "RAKUTEN_AFFILIATE_ID": "r-aff",
    "DEEPSEEK_API_KEY": "d-secret",
    "ANTHROPIC_API_KEY": "a-secret",
    "DATABASE_URL": "postgresql://u:p@h/db",
}


def build(tmp_path: Path, **options: bool) -> dict[str, str]:
    return worker_environment(SECRETS, tmp_path, tmp_path, "http://x", "token", "m", **options)


@pytest.mark.parametrize("name", sorted(SECRETS))
def test_offline_worker_environment_has_no_provider_key_or_secret(
    tmp_path: Path, name: str
) -> None:
    env = build(tmp_path)
    assert name not in env
    assert not any(value in SECRETS.values() for key, value in env.items() if key != name)


def test_live_worker_gets_only_the_data_provider_keys_it_executes_tools_with(
    tmp_path: Path,
) -> None:
    env = build(tmp_path, live=True)
    assert env["GOOGLE_MAPS_API_KEY"] == "g-secret" and env["RAKUTEN_APP_ID"] == "r-app"
    for name in ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "DATABASE_URL"):
        assert name not in env
    assert env["ANTHROPIC_AUTH_TOKEN"] == "token"  # 仅本地护栏的一次性令牌

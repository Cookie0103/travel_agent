"""测试共用：需要真实 Claude CLI 的用例统一跳过条件（与生产 find_cli 同一选取规则）。"""

import os

import pytest

from backend.limits import ProbeError
from backend.providers.claude_agent.environment import find_cli


def cli_available() -> bool:
    try:
        find_cli(os.environ)
    except ProbeError:
        return False
    return True


requires_claude_cli = pytest.mark.skipif(
    not cli_available(), reason="需要本机Claude CLI，离线用例不访问真实模型"
)

"""显式live评测读取本地线路配置；合成门禁在任何调用/数据库前停止。"""

import os
import sys
from pathlib import Path

import pytest

from backend.limits import ProbeError
from eval import run
from eval.cases import Case


@pytest.mark.usefixtures("allow_mocked_live")
def test_explicit_live_evaluation_loads_env_before_budget_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=synthetic-eval-key\n", encoding="utf-8")
    monkeypatch.setattr(run, "ROOT", tmp_path)
    # 注册撤销记录，dotenv新增的变量也必须随测试结束清理。
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-before-env")
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    monkeypatch.setattr(sys, "argv", ["eval.run", "--live"])
    case = Case(case_id="synthetic", source="test", adaptation="test", input="合成测试")
    monkeypatch.setattr(run, "load_suite", lambda *args: ([case], {}))
    seen: list[str | None] = []

    def check(root: Path, count: int) -> None:
        seen.append(os.environ.get("DEEPSEEK_API_KEY"))
        raise ProbeError("blocked", "合成门禁在预占前停止")

    monkeypatch.setattr(run, "check_evaluation_size", check)
    assert run.main() == 1
    assert seen == ["synthetic-eval-key"]

"""测试会话配置：默认把 pytest 临时目录放在被 git 忽略的 .cache 下。"""

import os
from pathlib import Path


def pytest_configure() -> None:
    # 系统临时目录的 pytest-of-<user> 可能被其他账户/沙箱占用而 PermissionError；
    # 显式设置（如 scripts/dev.py test 的每次运行目录）时不覆盖。
    if "PYTEST_DEBUG_TEMPROOT" not in os.environ:
        root = Path(__file__).resolve().parents[1] / ".cache" / "pytest-tmp"
        root.mkdir(parents=True, exist_ok=True)
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(root)

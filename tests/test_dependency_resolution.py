"""验证项目锁文件不受用户全局依赖日期策略影响；全程离线且不修改锁文件。"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_project_lock_remains_valid_with_older_user_cutoff(tmp_path: Path) -> None:
    """删掉项目覆盖会重新解析并拒绝现有锁文件，而不是静默更换依赖。"""
    config_root = tmp_path / "config"
    config = config_root / "uv" / "uv.toml"
    config.parent.mkdir(parents=True)
    config.write_text('exclude-newer = "2000-01-01T00:00:00Z"\n', encoding="utf-8")
    environment = dict(os.environ)
    environment["XDG_CONFIG_HOME"] = str(config_root)
    environment["APPDATA"] = str(config_root)
    # 不变量：测试项目配置优先级，不允许环境变量绕过项目设置。
    for key in ("UV_EXCLUDE_NEWER", "UV_CONFIG_FILE", "UV_NO_CONFIG"):
        environment.pop(key, None)
    lock = ROOT / "uv.lock"
    before = lock.read_bytes()
    result = subprocess.run(
        ["uv", "lock", "--check", "--offline"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert lock.read_bytes() == before

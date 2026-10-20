"""独立Compose离线演示入口；生成专用密码、保持卷，不接触用户模型配置。"""

import re
import secrets
import sys
from pathlib import Path

from scripts.dev import ROOT, run_command


def settings(root: Path = ROOT) -> Path:
    path = root / ".cache/demo.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write("DEMO_DB_PASSWORD=" + secrets.token_hex(32) + "\n")
    except FileExistsError:
        pass
    if not re.fullmatch(r"DEMO_DB_PASSWORD=[0-9a-f]{64}\n", path.read_text(encoding="utf-8")):
        raise ValueError("专用演示配置损坏；不能覆盖旧密码，请核对.cache/demo.env")
    return path


def main(action: str) -> int:
    if action not in {"stack-up", "stack-status", "stack-down"}:
        return 2
    if run_command(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=15):
        return 1
    try:
        path = settings()
    except (OSError, ValueError):
        print("unavailable: 演示配置不可读或损坏；原文件保留，未修改数据库")
        return 1
    base = [
        "docker",
        "compose",
        "--env-file",
        str(path),
        "--project-name",
        "travel-agent-demo",
        "--file",
        "docker-compose.demo.yml",
    ]
    commands = {
        "stack-up": ["up", "-d", "--wait", "--wait-timeout", "180"],
        "stack-status": ["ps", "--all"],
        "stack-down": ["down"],
    }
    # 先构建共享镜像，避免api/供应商误向公共仓库pull本地镜像名。
    if action == "stack-up" and run_command([*base, "build"], timeout=1200):
        return 1
    return run_command([*base, *commands[action]], timeout=240 if action == "stack-up" else 60)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]) if len(sys.argv) == 2 else 2)

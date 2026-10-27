"""检查本机开发前置条件；只读，失败项给出修复提示，退出码非零表示有未满足项。"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.persistence.database import configuration
from backend.providers.claude_agent.runtime import VERIFIED_COMPACTION_CONTROL

ROOT = Path(__file__).resolve().parents[1]
Read = Callable[[Sequence[str]], str | None]


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    hint: str = ""


def read_output(command: Sequence[str]) -> str | None:
    executable = shutil.which(command[0])
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, *command[1:]], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def major(output: str | None) -> int | None:
    try:
        return int((output or "").split()[0].lstrip("v").split(".")[0])
    except (IndexError, ValueError):
        return None


def tool_checks(read: Read) -> list[Check]:
    node, pnpm, uv, claude = (
        read(["node", "--version"]),
        read(["pnpm", "--version"]),
        read(["uv", "--version"]),
        read(["claude", "--version"]),
    )
    verified = sorted({cli for _, cli in VERIFIED_COMPACTION_CONTROL})
    cli = claude.split()[0] if claude else ""
    return [
        Check(
            "python",
            sys.version_info[:2] == (3, 12),
            sys.version.split()[0],
            "需要 Python 3.12：uv python install 3.12",
        ),
        Check("uv", uv is not None, uv or "未找到", "安装 uv：https://docs.astral.sh/uv/"),
        Check(
            "node",
            (major(node) or 0) >= 24,
            node or "未找到",
            "需要 Node 24+（前端与 CI 一致）",
        ),
        Check(
            "pnpm",
            major(pnpm) == 11,
            pnpm or "未找到",
            "需要 pnpm 11：corepack enable && corepack prepare pnpm@11.19.0 --activate",
        ),
        Check(
            "claude",
            cli in verified,
            f"CLI {cli}，已验证 {verified}" if cli else "未找到",
            f"安装已验证版本：npm install --global @anthropic-ai/claude-code@{verified[-1]}；"
            "新版本须先独立离线核验后才能加入白名单",
        ),
    ]


def postgres_check(config: Mapping[str, str]) -> Check:
    port = int(config.get("POSTGRES_PORT") or "5434")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            return Check("postgres", True, f"127.0.0.1:{port} 可连")
    except OSError:
        return Check(
            "postgres",
            False,
            f"127.0.0.1:{port} 不可连",
            "先启动 Docker Desktop，再运行 uv run python scripts/dev.py db-up",
        )


def temp_check(root: Path) -> Check:
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root):
            return Check("pytest-tmp", True, str(root))
    except OSError:
        return Check(
            "pytest-tmp",
            False,
            f"{root} 不可写",
            "设置 PYTEST_DEBUG_TEMPROOT 指向可写目录，或检查项目目录权限",
        )


def run_checks() -> list[Check]:
    root = Path(os.environ.get("PYTEST_DEBUG_TEMPROOT") or ROOT / ".cache" / "pytest-tmp")
    return [*tool_checks(read_output), postgres_check(configuration()), temp_check(root)]


def main() -> int:
    results = run_checks()
    for item in results:
        print(f"[{'ok' if item.ok else '!!'}] {item.name}: {item.detail}")
        if not item.ok:
            print(f"     -> {item.hint}")
    failed = [item.name for item in results if not item.ok]
    print("全部满足。" if not failed else f"未满足：{', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

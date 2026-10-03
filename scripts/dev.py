"""开发命令入口：为安装、检查、测试及本地数据库提供跨平台子进程调度。"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def configure_environment() -> None:
    """统一子进程编码和缓存位置，不要求用户修改 shell 环境。"""
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    os.environ.setdefault("UV_CACHE_DIR", str(ROOT / ".cache" / "uv"))
    os.environ.setdefault("PRE_COMMIT_HOME", str(ROOT / ".cache" / "pre-commit"))


def run_command(command: Sequence[str], *, timeout: int = 300) -> int:
    """让失败退出码原样传播，并给缺少可执行文件和超时以明确分类。"""
    print("+ " + " ".join(command), flush=True)
    try:
        return subprocess.run(list(command), cwd=ROOT, timeout=timeout, check=False).returncode
    except OSError:
        print(f"unavailable: 无法启动 {command[0]}，请检查安装和权限。", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print(f"timeout: {command[0]} 超过 {timeout} 秒，已停止。", file=sys.stderr)
        return 1


def run_sequence(commands: Sequence[Sequence[str]]) -> int:
    """前一步失败就停止，不能用后续命令的成功掩盖失败。"""
    for command in commands:
        result = run_command(command)
        if result:
            return result
    return 0


def record_blocked(reason: str) -> None:
    """把无法无人值守完成的环境操作记录到可恢复的仓库文件。"""
    path = ROOT / "docs" / "blocked" / "environment.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else "# 阻塞记录\n"
    if reason not in existing:
        stamp = datetime.now(UTC).isoformat()
        path.write_text(f"{existing}\n- {stamp} — {reason}\n", encoding="utf-8", newline="\n")


def run_tests() -> int:
    """每次测试使用新目录，避免用户终端与沙箱复用彼此无权限的 pytest 文件。"""
    parent = ROOT / ".cache" / "pytest-runs"
    try:
        parent.mkdir(parents=True, exist_ok=True)
        run_root = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    except OSError:
        print("unavailable: 无法创建测试临时目录，请检查项目目录写权限。", file=sys.stderr)
        return 1
    previous = os.environ.get("PYTEST_DEBUG_TEMPROOT")
    os.environ["PYTEST_DEBUG_TEMPROOT"] = str(run_root)
    try:
        # 不变量：新建目录不复用旧现场；缓存也必须属于本次运行。
        return run_command(
            [
                sys.executable,
                "-m",
                "pytest",
                "-m",
                "not live",
                "-o",
                f"cache_dir={run_root / 'cache'}",
            ]
        )
    finally:
        if previous is None:
            os.environ.pop("PYTEST_DEBUG_TEMPROOT", None)
        else:
            os.environ["PYTEST_DEBUG_TEMPROOT"] = previous


def db_up() -> int:
    """先检查 Docker 引擎，未就绪时记录阻塞而不等待人工启动。"""
    # 不变量：引擎不可用时，不执行 compose up。
    if run_command(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=15):
        record_blocked("dev db-up: Docker 引擎不可用；启动 Docker Desktop 后重试。")
        return 1
    return run_command(
        ["docker", "compose", "up", "-d", "--wait", "--wait-timeout", "60", "postgres"]
    )


def eval_dev(*, live: bool) -> int:
    """M0.6 实现前明确拒绝评测入口，不伪造结果。"""
    if not (ROOT / "eval" / "run.py").is_file():
        print("unavailable: eval.run 尚未实现，等待 M0.6。", file=sys.stderr)
        return 1
    command = [sys.executable, "-m", "eval.run", "--split", "dev"]
    if live:
        command.append("--live")
    return run_command(command)


def main(argv: Sequence[str] | None = None) -> int:
    """解析唯一开发命令并返回适合 CI 与 Git hook 的退出码。"""
    configure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("setup", "check", "test", "db-up", "db-migrate"):
        commands.add_parser(name)
    evaluation = commands.add_parser("eval-dev")
    evaluation.add_argument("--live", action="store_true", help="显式启用真实模型评测")
    args = parser.parse_args(argv)
    python = sys.executable
    match args.command:
        case "setup":
            return run_sequence(
                [["uv", "sync", "--locked"], [python, "-m", "pre_commit", "install"]]
            )
        case "check":
            return run_sequence(
                [
                    [python, "-m", "ruff", "check", "."],
                    [python, "-m", "ruff", "format", "--check", "."],
                    [python, "-m", "mypy", "--strict"],
                    ["lint-imports"],
                ]
            )
        case "test":
            # 不变量：dev test 总是排除 live，且不开放覆盖 marker 的透传参数。
            return run_tests()
        case "db-up":
            return db_up()
        case "db-migrate":
            return run_command(
                [
                    python,
                    "-m",
                    "alembic",
                    "-c",
                    "backend/persistence/alembic.ini",
                    "upgrade",
                    "head",
                ]
            )
        case "eval-dev":
            return eval_dev(live=args.live)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

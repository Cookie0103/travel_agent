"""开发命令入口：为安装、检查、测试及本地数据库提供跨平台子进程调度。"""

from __future__ import annotations

import argparse
import io
import os
import shutil
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


def run_command(
    command: Sequence[str], *, timeout: int | None = 300, cwd: Path | None = None
) -> int:
    """让失败退出码原样传播，并给缺少可执行文件和超时以明确分类。"""
    print("+ " + " ".join(command), flush=True)
    try:
        return subprocess.run(
            list(command), cwd=cwd or ROOT, timeout=timeout, check=False
        ).returncode
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


def test_path(value: str) -> str:
    """专项路径只允许仓库 tests 内的文件，不开放 pytest 任意参数透传。"""
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT / "tests") or path.suffix != ".py" or not path.is_file():
        raise argparse.ArgumentTypeError("专项测试必须是 tests/ 内的 Python 文件")
    return path.relative_to(ROOT).as_posix()


def run_tests(paths: Sequence[str] = (), keyword: str | None = None) -> int:
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
                "-q",
                *paths,
                *(["-k", keyword] if keyword else []),
                "-o",
                f"cache_dir={run_root / 'cache'}",
            ],
            # 整套PG/SDK回归已有约五分钟；外层预算不改变各操作自己的期限。
            timeout=600,
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


def web(command: str, *, webpack: bool = False) -> int:
    pnpm = shutil.which("pnpm.cmd" if os.name == "nt" else "pnpm")
    if pnpm is None:
        print("unavailable: 需要Node24+和pnpm11，见apps/web/README.md", file=sys.stderr)
        return 1
    if command == "web-generate":
        result = run_command([sys.executable, "-m", "scripts.export_web_schema"])
        if result:
            return result
    actions = {
        "web-setup": [["install", "--frozen-lockfile"]],
        "web-generate": [["run", "generate"]],
        "web-format": [["run", "format"]],
        "web-check": [["run", name] for name in ("typecheck", "lint", "test", "build")],
        "web": [["run", "dev"]],
    }
    for action in actions[command]:
        if webpack and action == ["run", "build"]:
            action = [*action, "--webpack"]
        result = run_command(
            [pnpm, *action], cwd=ROOT / "apps" / "web", timeout=None if command == "web" else 300
        )
        if result:
            return result
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """解析唯一开发命令并返回适合 CI 与 Git hook 的退出码。"""
    configure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "setup",
        "check",
        "format",
        "db-up",
        "db-migrate",
        "supplier",
        "web-setup",
        "web-generate",
        "web-format",
        "web",
        "stack-up",
        "stack-status",
        "stack-down",
    ):
        commands.add_parser(name)
    web_check = commands.add_parser("web-check")
    web_check.add_argument("--webpack", action="store_true")
    tests = commands.add_parser("test")
    tests.add_argument("--path", action="append", type=test_path, default=[])
    tests.add_argument("--keyword", help="只筛选测试名，live 门禁保持不变")
    api = commands.add_parser("api")
    api.add_argument("--live", action="store_true", help="显式允许已授权的真实模型消息")
    api.add_argument("--trace-cloud", action="store_true", help="显式上传脱敏 Trace")
    evaluation = commands.add_parser("eval-dev")
    evaluation.add_argument("--live", action="store_true", help="显式启用真实模型评测")
    probe = commands.add_parser("probe-hotel-sort")
    probe.add_argument("--live", action="store_true", help="显式允许最多2次乐天请求核实排序")
    smoke = commands.add_parser("smoke-langfuse-linkage")
    smoke.add_argument("--live", action="store_true")
    smoke.add_argument("--trace-cloud", action="store_true")
    v2 = commands.add_parser("eval-v2")
    v2.add_argument("--live", action="store_true")
    v2.add_argument("--trace-cloud", action="store_true")
    v2.add_argument("--repeat", type=int, choices=range(1, 4), default=3)
    v2.add_argument("--case-id", action="append", default=[])
    memory = commands.add_parser("eval-memory")
    memory.add_argument("--live", action="store_true")
    memory.add_argument("--trace-cloud", action="store_true")
    memory.add_argument("--repeat", type=int, choices=range(1, 4), default=1)
    memory.add_argument("--case-id", action="append", default=[])
    simulator = commands.add_parser("eval-simulator")
    simulator.add_argument("--live", action="store_true")
    simulator.add_argument("--trace-cloud", action="store_true")
    simulator.add_argument("--repeat", type=int, choices=range(1, 4), default=3)
    simulator.add_argument("--case-id", action="append", default=[])
    triage = commands.add_parser("eval-triage")
    triage.add_argument("results", type=Path)
    triage.add_argument("--live", action="store_true")
    triage.add_argument("--check-references", type=Path)
    triage.add_argument("--out", type=Path)
    rescore = commands.add_parser("eval-simulator-rescore")
    rescore.add_argument("results", type=Path)
    rescore.add_argument("--out", type=Path)
    rescore.add_argument("--hashes", type=Path)
    memory_rescore = commands.add_parser("eval-memory-rescore")
    memory_rescore.add_argument("results", type=Path)
    memory_rescore.add_argument("--out", type=Path)
    memory_rescore.add_argument("--hashes", type=Path)
    calibration = commands.add_parser("eval-calibration")
    calibration.add_argument("results", type=Path, nargs="+")
    calibration.add_argument("--live", action="store_true")
    calibration.add_argument("--threshold", type=int, choices=range(1, 6), default=3)
    human_sheet = commands.add_parser("eval-human-sheet")
    human_sheet.add_argument("--out", type=Path)
    human_score = commands.add_parser("eval-human-score")
    human_score.add_argument("csv", type=Path)
    human_score.add_argument("references", type=Path)
    publish = commands.add_parser("eval-publish-v2")
    publish.add_argument("results", type=Path, nargs="+")
    publish.add_argument("--triage", type=Path)
    publish.add_argument("--trace-cloud", action="store_true")
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
                    *[
                        [python, "-m", "mypy", "--strict", "--platform", platform]
                        for platform in ("win32", "linux", "darwin")
                    ],
                    ["lint-imports"],
                    [python, "scripts/check_docs.py"],
                ]
            )
        case "format":
            return run_command([python, "-m", "ruff", "format", "."])
        case "test":
            # 不变量：dev test 总是排除 live，且不开放覆盖 marker 的透传参数。
            return run_tests(args.path, args.keyword)
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
        case "eval-memory":
            if args.trace_cloud and not args.live:
                return 2
            if not args.live:
                from eval.suites import load_suite

                cases, _ = load_suite(ROOT, "v2-memory", "dev")
                print(f"prepared: {len(cases)}记忆案例；未发模型调用，确定性不变量由专项测试验证")
                return 0
            command = [
                python,
                "-m",
                "eval.run",
                "--suite",
                "v2-memory",
                "--database",
                "--repeat",
                str(args.repeat),
                "--max-attempts",
                "12",
                "--live",
            ]
            if args.trace_cloud:
                command.append("--trace-cloud")
            for case_id in args.case_id:
                command.extend(["--case-id", case_id])
            return run_command(command, timeout=7200)
        case "eval-simulator":
            if args.trace_cloud and not args.live:
                return 2
            command = [python, "-m", "eval.simulator", "--repeat", str(args.repeat)]
            if args.live:
                command.append("--live")
            if args.trace_cloud:
                command.append("--trace-cloud")
            for case_id in args.case_id:
                command.extend(["--case-id", case_id])
            return run_command(command, timeout=14400)
        case "eval-triage":
            command = [python, "-m", "eval.triage", str(args.results)]
            if args.check_references:
                command.extend(["--check-references", str(args.check_references)])
            if args.out:
                command.extend(["--out", str(args.out)])
            if args.live:
                command.append("--live")
            return run_command(command, timeout=7200)
        case "eval-simulator-rescore" | "eval-memory-rescore":
            command = [python, "-m", "eval.rescore_simulator", str(args.results)]
            if args.hashes:
                command.extend(["--hashes", str(args.hashes)])
            if args.out:
                command += ["--out", str(args.out)]
            return run_command(command)
        case "eval-calibration":
            command = [
                python,
                "-m",
                "eval.calibration",
                *[str(p) for p in args.results],
                "--threshold",
                str(args.threshold),
            ]
            if args.live:
                command.append("--live")
            return run_command(command, timeout=7200)
        case "eval-human-sheet":
            command = [python, "-m", "eval.human_sheet"]
            if args.out:
                command.extend(["--out", str(args.out)])
            return run_command(command)
        case "eval-human-score":
            return run_command(
                [python, "-m", "eval.calibrate_v2", str(args.csv), str(args.references)]
            )
        case "eval-publish-v2":
            command = [python, "-m", "eval.publish_v2", *[str(p) for p in args.results]]
            if args.triage:
                command.extend(["--triage", str(args.triage)])
            if args.trace_cloud:
                command.append("--trace-cloud")
            return run_command(command, timeout=300)
        case "eval-v2":
            if args.trace_cloud and not args.live:
                return 2
            command = [
                python,
                "-m",
                "eval.run",
                "--suite",
                "v2",
                "--database",
                "--repeat",
                str(args.repeat),
                "--max-attempts",
                "12",
            ]
            if args.live:
                command.append("--live")
            if args.trace_cloud:
                command.append("--trace-cloud")
            for case_id in args.case_id:
                command.extend(["--case-id", case_id])
            return run_command(command, timeout=7200 if args.live else 600)
        case "probe-hotel-sort":
            if not args.live:
                print("需要显式 --live；未发请求。", file=sys.stderr)
                return 2
            return run_command([python, "-m", "scripts.probe_hotel_sort", "--live"])
        case "smoke-langfuse-linkage":
            if not (args.live and args.trace_cloud):
                print("需要显式 --live --trace-cloud；未发请求。", file=sys.stderr)
                return 2
            return run_command(
                [python, "-m", "scripts.smoke_langfuse_linkage", "--live", "--trace-cloud"]
            )
        case "api":
            command = [python, "-m", "backend.server"]
            if args.live:
                command.append("--live")
            if args.trace_cloud:
                command.append("--trace-cloud")
            return run_command(command, timeout=None)
        case "supplier":
            return run_command([python, "-m", "mock_supplier.server"], timeout=None)
        case "web" | "web-setup" | "web-check" | "web-generate" | "web-format":
            return web(args.command, webpack=getattr(args, "webpack", False))
        case "stack-up" | "stack-status" | "stack-down":
            return run_command([python, "-m", "scripts.stack", args.command], timeout=None)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

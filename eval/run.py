"""21 条初始任务的可恢复评测入口；复用 CLI 的 Agent 与 live 费用守卫。"""

import argparse
import asyncio
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from backend.agent.fixture_runtime import FixtureRuntime
from backend.agent.runtime import Agent
from backend.domain.execution import RunContext, RunResult, RuntimeEvent
from backend.providers.claude_agent.live import run_live
from backend.providers.probe.settings import ProbeError
from backend.tools.search import DEFINITIONS, SearchExecutor
from eval.cases import Case, load_cases
from eval.graders import Observation, grade
from eval.persona import rules as persona_rules

ROOT = Path(__file__).resolve().parents[1]


async def observe(
    case: Case, live: bool, context: RunContext
) -> tuple[Observation, dict[str, object]]:
    if live:
        report = run_live(case.input, context, ROOT)
        results = TypeAdapter(list[RunResult]).validate_python(report.get("results", []))
        events = TypeAdapter(tuple[RuntimeEvent, ...]).validate_python(report.get("events", []))
        status = "completed" if report.get("status") == "success" else "failed"
        return Observation(status, results[-1].outcome.text if results else "", events), report
    events_list: list[RuntimeEvent] = []
    agent = Agent(FixtureRuntime(SearchExecutor()))
    result = await agent.run(context, case.input, events_list.append)
    return Observation(
        "failed" if result.outcome.code else "completed", result.outcome.text, tuple(events_list)
    ), {"identity": asdict(agent.runtime.identity)}


async def run_cases(cases: list[Case], directory: Path, *, live: bool = False) -> dict[str, object]:
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "manifest.json").write_text(
        json.dumps(manifest(cases), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    mode = "live" if live else "offline_fixture"
    print(f"模式：{mode}；规则分不代表完整任务质量，离线分不代表模型能力。")
    rows: list[dict[str, object]] = []
    passed = 0
    stop = False
    with (
        (directory / "results.jsonl").open("w", encoding="utf-8", newline="\n") as handle,
        (directory / "attempts.jsonl").open("w", encoding="utf-8", newline="\n") as attempts,
    ):
        for case in cases:
            context = RunContext(uuid4())
            if not stop:
                # 不变量：先落盘 case 与会话目录关联，再允许付费；未完成记录不可自动重试。
                attempts.write(
                    json.dumps({"case_id": case.case_id, "context": asdict(context)}, default=str)
                    + "\n"
                )
                attempts.flush()
                os.fsync(attempts.fileno())
            row: dict[str, object] = (
                await run_case(case, context, live=live)
                if not stop
                else {
                    "case_id": case.case_id,
                    "status": "not_run",
                    "reason": "prior_runtime_error",
                }
            )
            rows.append(row)
            passed += int(row["status"] == "passed")
            stop |= row["status"] == "error"
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            print(
                f"{case.case_id:<26} {row['status']:<8} {row.get('failed_checks', '')}", flush=True
            )
    evaluated = sum(row["status"] in {"passed", "failed"} for row in rows)
    summary: dict[str, object] = {
        "mode": mode,
        "case_count": len(cases),
        "evaluated": evaluated,
        "passed": passed,
        "errors": sum(r["status"] == "error" for r in rows),
        "not_run": sum(r["status"] == "not_run" for r in rows),
        "rule_pass_rate": passed / evaluated if evaluated else None,
        "repetitions": 1,
        "data_version": "kyoto-fixture-v1",
        "limitations": [
            "规则匹配不证明事实/相关性",
            "未实现的业务按原标准失败",
            "离线为固定工具脚本",
        ],
    }
    (directory / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"规则通过：{passed}/{evaluated}；结果：{directory}")
    return summary


async def run_case(case: Case, context: RunContext, *, live: bool) -> dict[str, object]:
    start = time.perf_counter()
    try:
        actual, report = await observe(case, live, context)
    except (ProbeError, ValueError, OSError):
        return {"case_id": case.case_id, "status": "error", "reason": "runtime_unavailable"}
    checks = grade(case, actual)
    return {
        "case_id": case.case_id,
        "status": "error"
        if actual.status != "completed"
        else "passed"
        if all(checks.values())
        else "failed",
        "checks": checks,
        "persona_checks": persona_rules(
            actual.text, emotional=case.case_id.startswith("emotional-")
        ),
        "failed_checks": [k for k, value in checks.items() if not value],
        "elapsed_seconds": round(time.perf_counter() - start, 3),
        "tools": [e.tool_name for e in actual.events if e.kind == "tool_started"],
        "text": actual.text,
        "identity": report.get("identity"),
        "http_attempts": report.get("http_attempts", 0),
        "requests": report.get("requests", []),
        "run_accounted_cny": report.get("run_accounted_cny"),
        "trace_id": report.get("trace_id"),
        "trace_status": report.get("trace_status"),
    }


def manifest(cases: list[Case]) -> dict[str, object]:
    """绑定实际源文件而非仅 HEAD；不读取 .env、vendor 或运行数据。"""
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
        check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
        check=True,
    ).stdout.strip()
    files = sorted(
        p
        for folder in ("backend", "data", "eval")
        for p in (ROOT / folder).rglob("*")
        if p.suffix in {".py", ".md", ".json", ".jsonl"} and "__pycache__" not in p.parts
    )
    files += [ROOT / "pyproject.toml", ROOT / "uv.lock"]
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "code_commit": commit,
        "worktree_dirty": bool(dirty),
        "sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        },
        "selected_cases": [c.model_dump() for c in cases],
        "schema_sha256": hashlib.sha256(
            json.dumps([asdict(d) for d in DEFINITIONS], sort_keys=True).encode()
        ).hexdigest(),
        "pricing": "backend/providers/probe/settings.py; CNY peak price; hash above",
        "skills": [],
        "runtime_versions": "recorded per case from actual worker identity",
    }


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="旅行任务规则评测；默认离线，不把规则分当模型质量")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--live", action="store_true", help="使用已授权 DeepSeek；产生费用")
    parser.add_argument("--case-id", action="append", help="只运行指定用例；不改变完整集")
    arguments = parser.parse_args()
    try:
        cases = load_cases(ROOT / "eval" / "cases" / "datamind_adapted.jsonl", arguments.split)
        if arguments.case_id:
            if set(arguments.case_id) - {c.case_id for c in cases}:
                raise ValueError("case_id 不存在")
            cases = [c for c in cases if c.case_id in arguments.case_id]
        name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        summary = asyncio.run(
            run_cases(cases, ROOT / ".cache" / "eval" / name, live=arguments.live)
        )
    except (ValueError, OSError, subprocess.SubprocessError):
        print("评测未完成：用例规格或输出目录不可用。")
        return 1
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

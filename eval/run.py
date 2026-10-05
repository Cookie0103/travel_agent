"""版本化自然语言任务的可恢复评测入口；复用CLI的Agent与live费用守卫。"""

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
from typing import TextIO, get_args
from uuid import uuid4

import psycopg
from pydantic import TypeAdapter

from backend.agent.fixture_runtime import FixtureRuntime
from backend.agent.runtime import Agent
from backend.domain.execution import RunContext, RunResult, RuntimeEvent
from backend.persistence.database import configuration, database_url
from backend.persistence.temporary import temporary_database
from backend.providers.claude_agent.evaluation import (
    EvaluationVariant,
    evaluation_definitions,
    evaluation_metadata,
    validate_variant,
)
from backend.providers.claude_agent.limits import ProbeError
from backend.providers.claude_agent.live import check_evaluation_size, run_live
from backend.services.common import ServiceError
from backend.tools.contracts import ToolDefinition
from backend.tools.search import DEFINITIONS, SearchExecutor
from backend.tools.travel import DEFINITIONS as TRAVEL_DEFINITIONS
from backend.tools.workflow import WORKFLOWS, WorkflowName
from eval.business_metrics import BusinessMetrics
from eval.cases import Case
from eval.database import DatabaseEvaluation, database_evaluation, selector_runner
from eval.diagnostics import diagnose
from eval.graders import Observation, grade
from eval.metrics import first_progress_seconds, tool_call_accuracy
from eval.persona import rules as persona_rules
from eval.report import measured_summary
from eval.suites import load_suite

ROOT = Path(__file__).resolve().parents[1]


async def observe(
    case: Case,
    live: bool,
    context: RunContext,
    *,
    business: DatabaseEvaluation | None = None,
    workflow: WorkflowName | None = None,
    max_attempts: int = 4,
    variant: EvaluationVariant = "full",
) -> tuple[Observation, dict[str, object]]:
    validate_variant(variant, database=business is not None, workflow=workflow)
    if variant != "full" and (not live or not business):
        raise ValueError("单因素对照需要实际SDK和独立业务会话")
    if live:
        report = (
            await asyncio.to_thread(
                run_live,
                case.input,
                context,
                ROOT,
                database_dsn=business.dsn(),
                workflow=workflow,
                max_attempts=max_attempts,
                supplier_url=business.supplier_url,
                evaluation_variant=variant,
            )
            if business
            else run_live(case.input, context, ROOT)
        )
        results = TypeAdapter(list[RunResult]).validate_python(report.get("results", []))
        events = TypeAdapter(tuple[RuntimeEvent, ...]).validate_python(report.get("events", []))
        status = "completed" if report.get("status") == "success" else "failed"
        return Observation(status, results[-1].outcome.text if results else "", events), report
    if business:
        return await business.observe(case, context, workflow)
    events_list: list[RuntimeEvent] = []
    agent = Agent(FixtureRuntime(SearchExecutor()))
    result = await agent.run(context, case.input, events_list.append)
    return Observation(
        "failed" if result.outcome.code else "completed", result.outcome.text, tuple(events_list)
    ), {"identity": asdict(agent.runtime.identity)}


async def run_cases(
    cases: list[Case],
    directory: Path,
    *,
    live: bool = False,
    business: DatabaseEvaluation | None = None,
    workflow: WorkflowName | None = None,
    max_attempts: int = 4,
    repeats: int = 1,
    suite: dict[str, object] | None = None,
    variant: EvaluationVariant = "full",
) -> dict[str, object]:
    validate_variant(variant, database=business is not None, workflow=workflow)
    if variant != "full" and (not live or not business):
        raise ValueError("单因素对照需实际SDK和业务评测；FixtureRuntime不能模拟优化效果")
    if type(repeats) is not int or not 1 <= repeats <= 3:
        raise ValueError("重复次数必须为1至3")
    if not business and (
        workflow
        or max_attempts != 4
        or any(
            case.initial_state or case.fault or case.business_checks or case.expected_tool_errors
            for case in cases
        )
    ):
        raise ValueError("固定流程或初始业务条件需要--database")
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                **manifest(cases, evaluation_definitions(variant, database=business is not None)),
                **evaluation_metadata(
                    variant, live=live, database=business is not None, workflow=workflow
                ),
                "business_database": business is not None,
                "business_metrics_version": 1,
                "database_name": business.sessions.database.engine.url.database
                if business
                else None,
                "catalog_sha256": business.catalog_sha256 if business else None,
                "data_version": business.data_version if business else "kyoto-fixture-v1",
                "max_http_attempts_per_case": max_attempts if live else 0,
                "repetitions": repeats,
                "evaluation_suite": suite,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    mode = (
        ("live_database" if live else "offline_database_fixture")
        if business
        else ("live" if live else "offline_fixture")
    )
    print(f"模式：{mode}；规则分不代表完整任务质量，离线分不代表模型能力。")
    rows: list[dict[str, object]] = []
    passed = 0
    stop = False
    with (
        (directory / "results.jsonl").open("w", encoding="utf-8", newline="\n") as handle,
        (directory / "attempts.jsonl").open("w", encoding="utf-8", newline="\n") as attempts,
    ):
        for repeat_index, case in (
            (index, case) for index in range(1, repeats + 1) for case in cases
        ):
            row: dict[str, object] = (
                await attempt_case(
                    case,
                    attempts,
                    live=live,
                    business=business,
                    workflow=workflow,
                    max_attempts=max_attempts,
                    repeat_index=repeat_index,
                    variant=variant,
                )
                if not stop
                else {
                    "case_id": case.case_id,
                    "status": "not_run",
                    "reason": "prior_runtime_error",
                }
            )
            row["repeat"] = repeat_index
            row.setdefault(
                "business_metrics", BusinessMetrics.for_case(case).model_dump(mode="json")
            )
            rows.append(row)
            passed += int(row["status"] == "passed")
            checks = row.get("checks")
            stop |= row["status"] == "error" or (
                isinstance(checks, dict)
                and any(
                    checks.get(key) is False
                    for key in (
                        "no_unconfirmed_plan_save",
                        "no_new_supplier_order",
                        "no_implicit_preference_write",
                    )
                )
            )
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
        "repetitions": repeats,
        "expected_attempts": len(cases) * repeats,
        **measured_summary(rows, repeats),
        "data_version": business.data_version if business else "kyoto-fixture-v1",
        "workflow": workflow or "autonomous",
        "evaluation_variant": variant,
        "limitations": [
            "规则匹配不证明事实/相关性",
            "DB模式共享应用业务工具，搜索模式只含搜索fixture",
            "离线为固定工具脚本，不是模型自主选择或固定编排效果",
            "案例声明的历史fixture标签保留；actual data_version与源文件hash记录本次实际数据",
        ],
    }
    (directory / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"规则通过：{passed}/{evaluated}；结果：{directory}")
    return summary


async def attempt_case(
    case: Case,
    attempts: TextIO,
    *,
    live: bool,
    business: DatabaseEvaluation | None,
    workflow: WorkflowName | None,
    max_attempts: int,
    repeat_index: int = 1,
    variant: EvaluationVariant = "full",
) -> dict[str, object]:
    try:
        context = await business.prepare(case) if business else RunContext(uuid4())
    except (ServiceError, ValueError, OSError):
        return {"case_id": case.case_id, "status": "error", "reason": "business_setup_failed"}
    # 不变量：先落盘实际PG身份与会话目录，再允许付费；未完成记录不可自动重试。
    attempts.write(
        json.dumps(
            {
                "case_id": case.case_id,
                "repeat": repeat_index,
                "context": asdict(context),
                "evaluation_variant": variant,
            },
            default=str,
        )
        + "\n"
    )
    attempts.flush()
    os.fsync(attempts.fileno())
    return await run_case(
        case,
        context,
        live=live,
        business=business,
        workflow=workflow,
        max_attempts=max_attempts,
        variant=variant,
    )


async def run_case(
    case: Case,
    context: RunContext,
    *,
    live: bool,
    business: DatabaseEvaluation | None = None,
    workflow: WorkflowName | None = None,
    max_attempts: int = 4,
    variant: EvaluationVariant = "full",
) -> dict[str, object]:
    start = time.perf_counter()
    started_at = datetime.now(UTC)
    if variant != "full":
        validate_variant(variant, database=business is not None, workflow=workflow)
        if not live or not business:
            raise ValueError("单因素对照需要实际SDK和独立业务会话")
    try:
        actual, report = (
            await observe(
                case,
                live,
                context,
                business=business,
                workflow=workflow,
                max_attempts=max_attempts,
                **({"variant": variant} if variant != "full" else {}),
            )
            if business
            else await observe(case, live, context)
        )
    except (ProbeError, ServiceError, ValueError, OSError):
        return {"case_id": case.case_id, "status": "error", "reason": "runtime_unavailable"}
    checks = grade(case, actual)
    verification_failed = False
    content_record: dict[str, object] | None = None
    business_metrics = BusinessMetrics.for_case(case)
    if business:
        try:
            assessment = await business.assess(case, context, actual)
            checks.update(assessment.checks)
            business_metrics = assessment.metrics
            content_record = (await business.content_record(case, context, actual.text)).model_dump(
                mode="json"
            )
        except (ServiceError, ValueError, OSError):
            checks["business_verification_available"] = False
            verification_failed = True
    trace_id = report.get("trace_id")
    return {
        "case_id": case.case_id,
        "status": "error"
        if verification_failed or actual.status not in case.allowed_final_statuses
        else "passed"
        if all(checks.values())
        else "failed",
        "checks": checks,
        "business_metrics": business_metrics.model_dump(mode="json"),
        "diagnosis": asdict(
            diagnose(
                actual.events,
                (),
                business_passed=all(checks.values()),
                trace_id=trace_id if isinstance(trace_id, str) else None,
            )
        ),
        "persona_checks": persona_rules(
            actual.text, emotional=case.case_id.startswith("emotional-")
        ),
        "failed_checks": [k for k, value in checks.items() if not value],
        "elapsed_seconds": round(time.perf_counter() - start, 3),
        "first_progress_seconds": first_progress_seconds(
            started_at, datetime.now(UTC), context, actual.events
        ),
        "tool_call_accuracy": tool_call_accuracy(case, actual.events),
        "tools": [e.tool_name for e in actual.events if e.kind == "tool_started"],
        "tool_count": sum(e.kind == "tool_started" for e in actual.events),
        "text": actual.text,
        "content_record": content_record,
        "identity": report.get("identity"),
        "http_attempts": report.get("http_attempts", 0),
        "requests": report.get("requests", []),
        "run_accounted_cny": report.get("run_accounted_cny"),
        "run_accounted": report.get("run_accounted"),
        "trace_id": report.get("trace_id"),
        "trace_status": report.get("trace_status"),
        "tokens": token_totals(report) if live else None,
        "accounting_currency": report.get("currency") if live else None,
    }


def token_totals(report: dict[str, object]) -> dict[str, int] | None:
    requests = report.get("requests")
    keys = (
        "input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "output_tokens",
    )
    if (
        not isinstance(requests, list)
        or not requests
        or report.get("http_attempts") != len(requests)
    ):
        return None
    if not all(
        isinstance(row, dict) and all(type(row.get(key)) is int and row[key] >= 0 for key in keys)
        for row in requests
    ):
        return None
    return {key: sum(row[key] for row in requests) for key in keys}


def schema_fingerprint(definitions: tuple[ToolDefinition, ...]) -> str:
    """绑定共享工具契约，运行与比较使用相同序列化。"""
    return hashlib.sha256(
        json.dumps([asdict(d) for d in definitions], sort_keys=True).encode()
    ).hexdigest()


def manifest(
    cases: list[Case], definitions: tuple[ToolDefinition, ...] = DEFINITIONS
) -> dict[str, object]:
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
        for folder in ("backend", "data", "eval", "mock_supplier")
        for p in (ROOT / folder).rglob("*")
        if p.suffix in {".py", ".md", ".json", ".jsonl"} and "__pycache__" not in p.parts
    )
    files += [
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        ROOT / "backend/persistence/alembic.ini",
        ROOT / "scripts/dev.py",
    ]
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "code_commit": commit,
        "worktree_dirty": bool(dirty),
        "sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        },
        "selected_cases": [c.model_dump() for c in cases],
        "schema_sha256": schema_fingerprint(definitions),
        "pricing": (
            "backend/providers/claude_agent/limits.py; original-currency upper bound; hash above"
        ),
        "skills": ["hotel-comparison", "itinerary-revision"]
        if definitions == TRAVEL_DEFINITIONS
        else [],
        "runtime_versions": "recorded per case from actual worker identity",
    }


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="旅行任务规则评测；默认离线，不把规则分当模型质量")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--suite", choices=["legacy", "frozen"], default="legacy")
    parser.add_argument(
        "--live", action="store_true", help="使用显式供应商；须有独立授权且产生费用"
    )
    parser.add_argument("--case-id", action="append", help="只运行指定用例；不改变完整集")
    parser.add_argument("--database", action="store_true", help="使用本地PG与应用旅行工具")
    parser.add_argument("--catalog-dir", type=Path, help="独立目录版本；仅--database legacy dev")
    parser.add_argument("--workflow", choices=sorted(WORKFLOWS), help="固定工具阶段；默认自主选择")
    parser.add_argument(
        "--variant",
        choices=get_args(EvaluationVariant.__value__),
        default="full",
        help="同SDK基线/单因素对照；压缩关闭限已验证SDK/CLI版本",
    )
    parser.add_argument("--max-attempts", type=int, choices=range(1, 13), default=4)
    parser.add_argument(
        "--repeat",
        type=int,
        choices=range(1, 4),
        default=1,
        help="预先定义独立重复；失败/安全异常后不重新付费",
    )
    arguments = parser.parse_args()
    try:
        if arguments.catalog_dir and (
            not arguments.database or arguments.suite != "legacy" or arguments.split != "dev"
        ):
            raise ValueError("独立目录只允许--database legacy dev，不改冻结或test数据")
        cases, suite = load_suite(ROOT, arguments.suite, arguments.split)
        if arguments.suite == "frozen" and not arguments.database:
            raise ValueError("冻结评测需要--database")
        if arguments.case_id:
            if set(arguments.case_id) - {c.case_id for c in cases}:
                raise ValueError("case_id 不存在")
            cases = [c for c in cases if c.case_id in arguments.case_id]
        name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]

        async def evaluate() -> dict[str, object]:
            if arguments.database:
                with temporary_database(database_url(configuration()), "eval") as target:
                    async with database_evaluation(
                        target, supplier=True, catalog_dir=arguments.catalog_dir
                    ) as business:
                        return await run_cases(
                            cases,
                            ROOT / ".cache" / "eval" / name,
                            live=arguments.live,
                            business=business,
                            workflow=arguments.workflow,
                            max_attempts=arguments.max_attempts,
                            repeats=arguments.repeat,
                            suite=suite,
                            variant=arguments.variant,
                        )
            return await run_cases(
                cases,
                ROOT / ".cache" / "eval" / name,
                live=arguments.live,
                repeats=arguments.repeat,
                suite=suite,
            )

        validate_variant(
            arguments.variant, database=arguments.database, workflow=arguments.workflow
        )
        if arguments.variant != "full" and (not arguments.live or not arguments.database):
            raise ValueError("单因素对照需--live --database，不使用FixtureRuntime冒充模型")
        if not arguments.database and (arguments.workflow or arguments.max_attempts != 4):
            raise ValueError("固定流程或自定义请求上限需要--database")
        if arguments.live:
            check_evaluation_size(ROOT, len(cases) * arguments.repeat)
        with selector_runner() as runner:
            summary = runner.run(evaluate())
    except (
        ProbeError,
        ServiceError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
        psycopg.Error,
    ):
        print("评测未完成：请检查用例冻结状态、本地数据库、输出目录或调用授权/预算。")
        return 1
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

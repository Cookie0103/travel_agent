"""离线比较原评测记录；完整配对、配置和执行版本核对后仅导出测量白名单。"""

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from backend.domain.execution import RunContext, RuntimeIdentity
from backend.limits import ProbeError, price_for, read_budget
from backend.providers.claude_agent.evaluation import (
    EvaluationVariant,
    evaluation_definitions,
    evaluation_metadata,
)
from backend.tools.workflow import WorkflowName
from eval.business_metrics import BusinessMetrics
from eval.cases import Case
from eval.report import distribution, measured_summary, rate
from eval.run import schema_fingerprint
from scripts.dev import configure_environment

ROOT = Path(__file__).resolve().parents[1]
type Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
type Repeat = Annotated[int, Field(strict=True, ge=1, le=3)]


class Manifest(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    selected_cases: tuple[Case, ...] = Field(min_length=1)
    sha256: dict[str, Hash] = Field(min_length=1)
    schema_sha256: Hash
    catalog_sha256: Hash | None
    evaluation_suite: dict[str, object] | None
    data_version: str
    business_database: bool = Field(strict=True)
    max_http_attempts_per_case: int = Field(strict=True, ge=1, le=12)
    repetitions: Repeat
    evaluation_variant: EvaluationVariant
    workflow: WorkflowName | Literal["autonomous"]
    comparison_group: str
    automatic_compaction: str
    sdk_resume_enabled: bool = Field(strict=True)
    skills: tuple[str, ...]
    pricing: str
    business_metrics_version: Literal[1] | None = None


class Row(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, allow_inf_nan=False)
    case_id: str = Field(pattern=r"^[a-z0-9-]+$")
    repeat: Repeat
    status: Literal["passed", "failed", "error", "not_run"]
    reason: str | None = None
    identity: RuntimeIdentity | None = None
    accounting_currency: Literal["CNY", "USD"] | None = None
    run_accounted: str | None = None
    http_attempts: int | None = Field(default=None, strict=True, ge=0)
    elapsed_seconds: float | None = Field(default=None, strict=True, ge=0)
    first_progress_seconds: float | None = Field(default=None, strict=True, ge=0)
    tool_call_accuracy: dict[str, object] | None = None
    tokens: dict[str, object] | None = None
    business_metrics: BusinessMetrics | None = None

    @model_validator(mode="after")
    def valid_measurement(self) -> "Row":
        if self.run_accounted is not None:
            read_budget(self.run_accounted)
        if self.identity is not None:
            identity = self.identity
            currency = price_for(identity.model).currency
            if identity.provider != ("deepseek" if currency == "CNY" else "anthropic"):
                raise ValueError("模型与供应商身份不符")
            if self.accounting_currency not in {None, currency}:
                raise ValueError("实际模型与计费币种不符")
            if not all(
                re.fullmatch(r"\d+\.\d+\.\d+", version)
                for version in (identity.sdk_version, identity.cli_version)
            ):
                raise ValueError("SDK/CLI版本不明确")
        return self

    @property
    def key(self) -> tuple[str, int]:
        return self.case_id, self.repeat


class Attempt(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    case_id: str
    repeat: Repeat
    context: RunContext
    evaluation_variant: EvaluationVariant

    @property
    def key(self) -> tuple[str, int]:
        return self.case_id, self.repeat


@dataclass(frozen=True)
class Batch:
    manifest: Manifest
    rows: tuple[Row, ...]
    attempts: tuple[Attempt, ...]
    measurements: dict[str, object]
    hashes: dict[str, str]


def load_batch(directory: Path) -> Batch:
    names = ("manifest.json", "results.jsonl", "attempts.jsonl", "summary.json")
    files = {name: (directory / name).read_bytes() for name in names}
    manifest = Manifest.model_validate_json(files["manifest.json"])
    rows = tuple(
        Row.model_validate_json(line) for line in files["results.jsonl"].splitlines() if line
    )
    attempts = tuple(
        Attempt.model_validate_json(line) for line in files["attempts.jsonl"].splitlines() if line
    )
    summary = TypeAdapter(dict[str, object]).validate_json(files["summary.json"])
    mode = "live_database" if manifest.business_database else "live"
    if summary.get("mode") != mode:
        raise ValueError("离线替身不能比较模型效果")
    expected = [
        (c.case_id, repeat)
        for repeat in range(1, manifest.repetitions + 1)
        for c in manifest.selected_cases
    ]
    if (
        len({c.case_id for c in manifest.selected_cases}) != len(manifest.selected_cases)
        or [r.key for r in rows] != expected
    ):
        raise ValueError("结果必须完整保持原用例与重复顺序")
    if manifest.business_metrics_version == 1:
        if any(r.business_metrics is None for r in rows):
            raise ValueError("新格式缺少业务观测")
        cases = {c.case_id: c for c in manifest.selected_cases}
        for row in rows:
            scope = BusinessMetrics.for_case(cases[row.case_id])
            assert row.business_metrics is not None
            if (scope.constraint.status == "not_applicable") != (
                row.business_metrics.constraint.status == "not_applicable"
            ) or (scope.booking == "not_applicable") != (
                row.business_metrics.booking == "not_applicable"
            ):
                raise ValueError("业务观测适用范围与冻结用例不符")
    elif any(r.business_metrics is not None for r in rows):
        raise ValueError("业务观测缺少格式版本")
    started = [
        r.key
        for r in rows
        if r.status != "not_run"
        and not (r.status == "error" and r.reason == "business_setup_failed")
    ]
    if [a.key for a in attempts] != started or any(
        a.evaluation_variant != manifest.evaluation_variant for a in attempts
    ):
        raise ValueError("尝试记录缺失、重复或配置不符")
    for name in ("user_id", "session_id", "run_id"):
        if len({getattr(a.context, name) for a in attempts}) != len(attempts):
            raise ValueError("每次运行必须独立身份")
    identities = {r.identity for r in rows if r.identity is not None}
    if len(identities) > 1:
        raise ValueError("同一批次混入不同模型/SDK身份")
    if any(
        r.http_attempts is not None and r.http_attempts > manifest.max_http_attempts_per_case
        for r in rows
    ):
        raise ValueError("实际请求超过声明的每例上限")
    workflow = None if manifest.workflow == "autonomous" else manifest.workflow
    metadata = evaluation_metadata(
        manifest.evaluation_variant,
        live=True,
        database=manifest.business_database,
        workflow=workflow,
    )
    if any(getattr(manifest, name) != value for name, value in metadata.items()):
        raise ValueError("配置不符合共享运行时定义")
    definitions = evaluation_definitions(
        manifest.evaluation_variant, database=manifest.business_database
    )
    skills = (
        ("hotel-comparison", "itinerary-revision")
        if manifest.business_database
        and manifest.evaluation_variant not in {"no_tools", "no_skills"}
        else ()
    )
    if manifest.schema_sha256 != schema_fingerprint(definitions) or manifest.skills != skills:
        raise ValueError("工具schema/Skills不符合声明配置")
    metrics = [r.model_dump(exclude={"reason"}) for r in rows]
    totals = rate(metrics)
    measured = measured_summary(metrics, manifest.repetitions)
    measurements = {
        **totals,
        **measured,
        "planned_pass_rate": sum(r.status == "passed" for r in rows) / len(rows),
    }
    cached = {
        **measured,
        "evaluated": totals["evaluated"],
        "passed": totals["passed"],
        "errors": totals["errors"],
        "not_run": totals["not_run"],
        "rule_pass_rate": totals["rule_pass_rate"],
        "expected_attempts": len(rows),
        "case_count": len(manifest.selected_cases),
        "repetitions": manifest.repetitions,
        "workflow": manifest.workflow,
        "evaluation_variant": manifest.evaluation_variant,
        "data_version": manifest.data_version,
    }
    # 旧冻结批次未捕获分项；只允许这一个新增摘要缺失，其他校核全部保留。
    if manifest.business_metrics_version is None and "business_metrics" not in summary:
        cached.pop("business_metrics")
    if any(summary.get(name) != value for name, value in cached.items()):
        raise ValueError("缓存摘要与原结果不符")
    return Batch(
        manifest,
        rows,
        attempts,
        measurements,
        {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
    )


def compare(first: Path, second: Path) -> dict[str, object]:
    a, b = load_batch(first), load_batch(second)
    same = (
        "business_metrics_version",
        "selected_cases",
        "sha256",
        "evaluation_suite",
        "catalog_sha256",
        "data_version",
        "business_database",
        "max_http_attempts_per_case",
        "repetitions",
        "pricing",
    )
    if any(getattr(a.manifest, name) != getattr(b.manifest, name) for name in same):
        raise ValueError("原用例/执行源码/数据/费用口径或重复配置不同，不能配对")
    for name in ("user_id", "session_id", "run_id"):
        if {getattr(row.context, name) for row in a.attempts} & {
            getattr(row.context, name) for row in b.attempts
        }:
            raise ValueError("两个实验组不能复用业务身份或会话")
    identities = [{r.identity for r in batch.rows if r.identity is not None} for batch in (a, b)]
    known = all(
        r.identity is not None for batch in (a, b) for r in batch.rows if r.status != "not_run"
    )
    if all(identities):
        ia, ib = next(iter(identities[0])), next(iter(identities[1]))
        if (ia.sdk_version, ia.cli_version) != (ib.sdk_version, ib.cli_version):
            raise ValueError("SDK/CLI版本不同，不能声称同运行时对照")
    costs: dict[str, list[Decimal]] = {}
    latency: list[float] = []
    outcomes: dict[str, int] = {}
    for ra, rb in zip(a.rows, b.rows, strict=True):
        key = f"{ra.status}->{rb.status}"
        outcomes[key] = outcomes.get(key, 0) + 1
        if ra.elapsed_seconds is not None and rb.elapsed_seconds is not None:
            latency.append(round(rb.elapsed_seconds - ra.elapsed_seconds, 6))
        if (
            ra.accounting_currency == rb.accounting_currency
            and ra.accounting_currency is not None
            and ra.run_accounted is not None
            and rb.run_accounted is not None
        ):
            costs.setdefault(ra.accounting_currency, []).append(
                read_budget(rb.run_accounted) - read_budget(ra.run_accounted)
            )
    return {
        "scope": "paired rule/configuration measurements; not semantic or human quality",
        "runtime_identity_complete": known,
        "source_hash_map_sha256": hashlib.sha256(
            json.dumps(a.manifest.sha256, sort_keys=True).encode()
        ).hexdigest(),
        "declared_configuration_changes": [
            name
            for name in (
                "evaluation_variant",
                "workflow",
                "comparison_group",
                "automatic_compaction",
                "sdk_resume_enabled",
                "schema_sha256",
                "skills",
            )
            if getattr(a.manifest, name) != getattr(b.manifest, name)
        ],
        "groups": {
            name: {
                "variant": batch.manifest.evaluation_variant,
                "workflow": batch.manifest.workflow,
                "comparison_group": batch.manifest.comparison_group,
                "files_sha256": batch.hashes,
                "measurement": batch.measurements,
            }
            for name, batch in (("a", a), ("b", b))
        },
        "paired": {
            "planned_n": len(a.rows),
            "outcomes": outcomes,
            "rule_pass_delta_b_minus_a": (
                sum(r.status == "passed" for r in b.rows)
                - sum(r.status == "passed" for r in a.rows)
            )
            / len(a.rows),
            "latency_delta_b_minus_a_seconds": distribution(latency),
            "original_currency_cost_delta_b_minus_a": {
                currency: {
                    "total": str(sum(values, Decimal(0))) if len(values) == len(a.rows) else None,
                    "measured_subtotal": str(sum(values, Decimal(0))),
                    "planned_n": len(a.rows),
                    "unknown_n": len(a.rows) - len(values),
                    **distribution([float(v) for v in values]),
                }
                for currency, values in costs.items()
            },
            "cost_unpaired_or_unknown_n": len(a.rows) - sum(map(len, costs.values())),
        },
        "limitations": [
            "All original failure/error/not_run rows retained in planned denominator",
            "Missing identity/semantic answers remain unknown; no causal quality claim",
            "B2 combines two switches; B0 also disables resume capability; "
            "fresh sessions do not use old checkpoints",
            "Different currencies are not converted or compared; cost is conservative accounting",
        ],
    }


def main() -> int:
    configure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs", nargs=2, type=Path, required=True, help="原目录或.cache/eval中的run id"
    )
    arguments = parser.parse_args()
    paths = [path if path.is_dir() else ROOT / ".cache/eval" / path for path in arguments.runs]
    try:
        output = compare(*paths)
    except (OSError, ValueError, ValidationError, ProbeError):
        print("比较未完成：原记录不完整、版本或配置不一致；不输出私有输入。")
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

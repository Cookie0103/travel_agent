"""以同组、同重复的试验记录运行两版 Skill 候选审核。"""

import argparse
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import TypeAdapter

from backend.domain.execution import scrub_internal_ids
from backend.tools.skill_config import SkillConfig
from eval.commerce.parameters import REGISTRY, Registry, load_parameters
from eval.commerce.score import Candidate, score
from eval.core.jsonl import read_jsonl
from eval.evolve.codex import Proposal, reflect
from eval.evolve.guarded import Evaluation, GuardedEdit, classify, evaluate_candidate
from eval.evolve.round import first_round
from eval.v3 import run
from eval.v3.cases import ROOT
from eval.v3.phase2_split import Split, split_identity
from eval.v3.skill_health import TRIGGERS

type Key = tuple[str, int]
type Row = dict[str, Any]


@dataclass(frozen=True)
class Evidence:
    directory: Path
    manifest: dict[str, Any]
    rows: dict[Key, Row]


def evidence(directory: Path, split: Split, *, archived_v1: bool = False) -> Evidence:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    ids = set(manifest["cases"])
    registered, sha256 = split_identity(split, archived_v1=archived_v1)
    if not ids <= registered:
        raise ValueError("自进化只读取所选反思或验证组的评测目录")
    if manifest.get("cases_sha256") != sha256 or (
        not archived_v1
        and (manifest.get("case_suite"), manifest.get("case_split")) != ("p2v2", split)
    ):
        raise ValueError("自进化运行清单与已冻结的题库版本或分区不符")
    rounds = manifest["repeat"]
    expected = {(case, repeat) for case in ids for repeat in range(1, rounds + 1)}
    soft = directory / "trials-with-soft.jsonl"
    records = run.latest_rows(read_jsonl(soft if soft.is_file() else directory / "trials.jsonl"))
    rows = {(str(row["case_id"]), int(str(row["repeat"]))): row for row in records}
    if (
        not expected
        or rows.keys() != expected
        or any(row.get("infra_error") for row in rows.values())
    ):
        raise ValueError(f"{split} 组须包含有完整结果的同题同重复试验")
    return Evidence(directory, manifest, rows)


def verify_start(source: Evidence, skills: SkillConfig) -> None:
    started = source.manifest.get("skills", {})
    if (
        started.get("variant", "full") != "full"
        or started.get("disabled")
        or started.get("versions", {}) != skills.versions()
    ):
        raise ValueError("基线评测清单的 Skill 配置与指定起点不一致")


def compare_provenance(
    source: Evidence, candidate: Evidence, skills: SkillConfig, *, same_profile: bool
) -> None:
    if source.rows.keys() != candidate.rows.keys() or any(
        row.get("seed_id") != candidate.rows[key].get("seed_id") for key, row in source.rows.items()
    ):
        raise ValueError("候选须使用与基线相同的题、种子和重复次数")
    for field in ("cases_sha256", "hotel_snapshot", "live", "local_model", "judge", "judge_check"):
        if source.manifest.get(field) != candidate.manifest.get(field):
            raise ValueError(f"候选的 {field} 与基线不一致")
    if same_profile and source.manifest.get("profile") != candidate.manifest.get("profile"):
        raise ValueError("候选的运行 profile 与基线不一致")
    if candidate.manifest.get("skills", {}).get("versions") != skills.versions():
        raise ValueError("候选评测清单的 Skill 哈希与实际生成的候选不一致")


def replay(
    source: Evidence,
    split: Split,
    directory: Path,
    candidate_run: Path | None,
    *,
    archived_v1: bool = False,
) -> Evidence:
    if candidate_run is None:
        if source.manifest.get("live") or source.manifest.get("hotel_snapshot"):
            raise ValueError("历史在线或专有酒店快照结果须提供同来源的候选评测目录")
        parent = directory / "replay"
        command = [
            "--split",
            split,
            "--repeat",
            str(source.manifest["repeat"]),
            "--candidate-skills",
            str(directory),
            "--no-judge",
            *[
                part
                for case in sorted({key[0] for key in source.rows})
                for part in ("--case-id", case)
            ],
        ]
        if profile := source.manifest.get("profile"):
            command.extend(("--profile", profile))
        if source.manifest.get("local_model"):
            command.append("--local-model")
        if run.main(command, run_parent=parent):
            raise ValueError("候选本机回放失败")
        (candidate_run,) = parent.iterdir()
    candidate = evidence(candidate_run, split, archived_v1=archived_v1)
    compare_provenance(
        source,
        candidate,
        SkillConfig(directory=directory),
        same_profile=bool(source.manifest.get("live") or source.manifest.get("local_model")),
    )
    return candidate


def transcripts(source: Evidence) -> dict[str, str]:
    folder = source.directory.resolve() / "transcripts"
    by_case: dict[str, list[str]] = {}
    for (case_id, repeat), row in sorted(source.rows.items()):
        path = (source.directory / row["transcript_path"]).resolve()
        if path != folder / f"{case_id}-{repeat}.txt":
            raise ValueError("反思轨迹必须对应同题同重复的记录")
        by_case.setdefault(case_id, []).append(scrub_internal_ids(path.read_text(encoding="utf-8")))
    return {case_id: "\n\n".join(values) for case_id, values in by_case.items()}


def observation(row: Row, parameters: Registry) -> Evaluation:
    sheet = row["commerce"]
    soft_values = row.get("commerce_soft", {}).get("by_hotel", {})
    hard = {c["id"] for c in row["checks"] if c["tier"] == "hard" and c["outcome"] == "fail"}
    violations = hard | {v["code"] for v in row["rule_gate"]["violations"]}
    invalid = set(sheet["violations"]) - {"partner_share", "partner_relevance"}
    groups = []
    explanation = []
    for group in sheet["groups"]:
        hotels = []
        for hotel in group["inputs"]:
            values = soft_values.get(f"{group['segment']}:{hotel['id']}", {})
            explanation.extend(values.values())
            hotels.append(Candidate.model_validate({**hotel, "soft_probabilities": values}))
        groups.append(score(hotels, group["budget_jpy"], group["persona"], parameters))
    expected = frozenset(
        name
        for name, triggers in TRIGGERS.items()
        if any(trigger.case_id == row["case_id"] and trigger.expected for trigger in triggers)
    )
    return Evaluation(
        case_id=row["case_id"],
        repeat=row["repeat"],
        seed_id=row.get("seed_id"),
        violations=frozenset(violations),
        blocked=not row["rule_gate"]["passed"],
        score=sum(group.total_jpy for group in groups)
        if not invalid and all(group.passed for group in groups)
        else 0.0,
        probability=1 - math.prod(group.no_booking for group in groups),
        soft=mean(explanation) if explanation else None,
        soft_applicable=bool(row.get("soft_facts")),
        expected_skills=expected,
        loaded_skills=frozenset(value["name"] for value in row["skills"]),
        weak_components=frozenset(row.get("weak_components", ())),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    versions = parser.add_subparsers(dest="version", required=True)
    first = versions.add_parser("first", help="第一版反思组回放")
    proposer = first.add_mutually_exclusive_group(required=True)
    proposer.add_argument("--proposal", type=Path)
    proposer.add_argument("--use-codex", action="store_true", help="显式请求 Codex CLI 生成提案")
    guarded = versions.add_parser("guarded", help="第二版在验证组应用四道闸")
    guarded.add_argument("--reflection-run", type=Path, required=True)
    guarded.add_argument("--edit", type=Path, required=True)
    for command in (first, guarded):
        command.add_argument("--baseline", type=Path, required=True)
        command.add_argument("--candidate-run", type=Path)
        command.add_argument(
            "--archived-v1", action="store_true", help="复核已归档 v1 的同分区成对结果"
        )
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--skills", type=Path)
        command.add_argument(
            "--parameters", type=Path, default=REGISTRY.with_name("parameters-rakuten-v1.json")
        )
    args = parser.parse_args(argv)
    if args.archived_v1 and (args.candidate_run is None or getattr(args, "use_codex", False)):
        parser.error("已归档 v1 只复核已有运行，须提供 --candidate-run 和已有提案")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".cache") or output.exists():
        parser.error("输出必须是项目 .cache 下的新目录")
    try:
        skills = SkillConfig(directory=args.skills)
        parameters = load_parameters(args.parameters)
        if args.version == "first":
            baseline = evidence(args.baseline, "reflection", archived_v1=args.archived_v1)
            verify_start(baseline, skills)
            propose: Callable[[dict[str, object]], Proposal]
            if args.use_codex:
                propose = reflect
                texts = transcripts(baseline)
            else:
                proposal = Proposal.model_validate_json(args.proposal.read_bytes())

                def local_proposal(_payload: dict[str, object]) -> Proposal:
                    return proposal

                propose = local_proposal
                texts = {}
            result = first_round(
                output,
                skills,
                list(baseline.rows.values()),
                texts,
                parameters,
                lambda directory, _tasks: list(
                    replay(
                        baseline,
                        "reflection",
                        directory,
                        args.candidate_run,
                        archived_v1=args.archived_v1,
                    ).rows.values()
                ),
                propose=propose,
                archived_v1=args.archived_v1,
            )
            print(f"审核页 {output / 'review.md'}，候选分数提高 {result.kept}")
        else:
            anchor = evidence(args.reflection_run, "reflection", archived_v1=args.archived_v1)
            verify_start(anchor, skills)
            issue = classify([observation(row, parameters) for row in anchor.rows.values()])
            if issue is None:
                raise ValueError("反思组缺少可归类的失败")
            baseline = evidence(args.baseline, "validation", archived_v1=args.archived_v1)
            verify_start(baseline, skills)
            target = issue.code.removeprefix("component:")
            target_cases = frozenset(
                row["case_id"]
                for row in baseline.rows.values()
                if any(check["id"] == target for check in row["checks"])
                or any(v["code"] == target for v in row["rule_gate"]["violations"])
                or target in row.get("weak_components", ())
            )
            edit = TypeAdapter(GuardedEdit).validate_json(args.edit.read_bytes())
            checked = evaluate_candidate(
                output,
                skills,
                edit,
                issue.code,
                target_cases,
                [observation(row, parameters) for row in baseline.rows.values()],
                lambda directory: [
                    observation(row, parameters)
                    for row in replay(
                        baseline,
                        "validation",
                        directory,
                        args.candidate_run,
                        archived_v1=args.archived_v1,
                    ).rows.values()
                ],
            )
            print(f"审核页 {checked.review}，四道闸通过 {checked.gates.passed}")
    except (KeyError, OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

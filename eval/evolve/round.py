"""第一版反思闭环。接受的改动只保存在本次候选目录。"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any, get_args

from backend.domain.tool_facts import EXPERIMENTAL_SKILLS, SkillName
from backend.tools.skill_config import SkillConfig
from eval.commerce.parameters import Registry
from eval.commerce.score import rescore
from eval.evolve.codex import Proposal, reflect
from eval.v3.phase2_split import split_identity


@dataclass(frozen=True)
class Outcome:
    skill: str
    self_assessment: str
    baseline: float
    candidate: float
    kept: bool
    candidate_directory: str
    note: str


def _index(
    rows: Sequence[Mapping[str, Any]], reflection: frozenset[str]
) -> dict[tuple[str, int], Mapping[str, Any]]:
    indexed = {}
    for row in rows:
        case = row["case_id"]
        if (
            case not in reflection
            or row.get("infra_error")
            or not isinstance(row.get("commerce"), dict)
        ):
            raise ValueError("反思闭环只接受完整的反思题结果")
        key = case, row["repeat"]
        if key in indexed:
            raise ValueError("存在重复的反思试验")
        indexed[key] = row
    if not indexed:
        raise ValueError("需要反思题的基线结果")
    return indexed


def first_round(
    root: Path,
    skills: SkillConfig,
    baseline: Sequence[Mapping[str, Any]],
    transcripts: Mapping[str, str],
    configuration: Registry,
    rerun: Callable[[Path, tuple[tuple[str, int], ...]], Sequence[Mapping[str, Any]]],
    *,
    propose: Callable[[dict[str, object]], Proposal] = reflect,
    archived_v1: bool = False,
) -> Outcome:
    reflection, _ = split_identity("reflection", archived_v1=archived_v1)
    previous = _index(baseline, reflection)
    if not transcripts.keys() <= {case for case, _ in previous}:
        raise ValueError("反思输入含未参与对照的题")
    known = get_args(SkillName)
    experimental = skills.candidate_names()
    texts = {
        name: skills.path(name).read_text(encoding="utf-8") for name in (*known, *experimental)
    }
    proposal = propose({"skills": texts, "reflection_transcripts": dict(transcripts)})
    if proposal.skill in known:
        texts[proposal.skill] = proposal.markdown
    else:
        slot = (
            proposal.skill
            if proposal.skill in experimental
            else next((name for name in EXPERIMENTAL_SKILLS if name not in experimental), None)
        )
        if slot is None:
            raise ValueError("三轮对照的新增候选位置已经用完")
        texts[slot] = f"触发：{proposal.trigger}\n名称：{proposal.skill}\n\n{proposal.markdown}"
    directory = root / "candidate"
    directory.mkdir(parents=True, exist_ok=False)
    for name, text in texts.items():
        (directory / (name + ".md")).write_text(text, encoding="utf-8")
    policy = configuration.policy.model_copy(
        update={"max_partner_share": 1.0, "min_partner_relevance": 0.0, "gamma": 0.0}
    )
    weak = configuration.model_copy(update={"policy": policy})
    original_score = mean(
        rescore(row["commerce"], weak, apply_trust=False) for row in previous.values()
    )
    completed = _index(rerun(directory, tuple(previous)), reflection)
    if previous.keys() != completed.keys():
        raise ValueError("候选须按同题、同重复的预算重跑")
    candidate_score = mean(
        rescore(row["commerce"], weak, apply_trust=False) for row in completed.values()
    )
    note = "已完成反思题的成对重跑"
    result = Outcome(
        proposal.skill,
        proposal.self_assessment,
        original_score,
        candidate_score,
        candidate_score > original_score,
        str(directory),
        note,
    )
    (root / "report.json").write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (root / "review.md").write_text(
        f"# {proposal.skill}\n\n{note}\n\n基线 {original_score:.4f}，候选 {candidate_score}。"
        f"保留 {result.kept}。\n\n## 模型自评\n\n{proposal.self_assessment}\n\n"
        f"## 候选全文\n\n{proposal.markdown}\n",
        encoding="utf-8",
    )
    return result

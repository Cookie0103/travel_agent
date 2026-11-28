"""第二版候选的单句改动、四道闸及审核记录。"""

import hashlib
import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from tempfile import NamedTemporaryFile, mkdtemp
from typing import get_args

from backend.domain.tool_facts import EXPERIMENTAL_SKILLS, SkillName
from backend.tools.skill_config import SkillConfig
from eval.core.paired import Difference, Trial, compare

_SENTENCE_END = re.compile(r"(?<=[。！？])|(?<=[.!?])(?=\s|$)|\r?\n")


@dataclass(frozen=True)
class Evaluation:
    case_id: str
    repeat: int
    seed_id: str | None
    violations: frozenset[str]
    blocked: bool
    score: float
    probability: float
    soft: float | None
    soft_applicable: bool
    expected_skills: frozenset[str] = frozenset()
    loaded_skills: frozenset[str] = frozenset()
    weak_components: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Issue:
    code: str
    case_ids: tuple[str, ...]
    signal: str


@dataclass(frozen=True)
class Gates:
    target: bool
    regression: bool
    components: bool
    coexistence: bool
    target_before: int
    target_after: int
    other_pass_rate: Difference
    other_score: Difference
    probability_before: float
    probability_after: float
    soft_before: float | None
    soft_after: float | None

    @property
    def passed(self) -> bool:
        return self.target and self.regression and self.components and self.coexistence


@dataclass(frozen=True)
class GuardedEdit:
    skill: str
    old: str
    new: str
    trigger: str | None = None
    trigger_examples: tuple[str, ...] = ()
    uncovered_reason: str = ""


@dataclass(frozen=True)
class CandidateResult:
    directory: Path
    review: Path
    gates: Gates
    best_directory: Path | None


def classify(rows: Sequence[Evaluation]) -> Issue | None:
    for attribute in ("violations", "weak_components"):
        affected: dict[str, set[str]] = {}
        for row in rows:
            for code in getattr(row, attribute):
                affected.setdefault(code, set()).add(row.case_id)
        if affected:
            selected = min(affected, key=lambda code: (-len(affected[code]), code))
            code = selected if attribute == "violations" else f"component:{selected}"
            return Issue(code, tuple(sorted(affected[selected])), attribute)
    return None


def assess(
    before: Sequence[Evaluation],
    after: Sequence[Evaluation],
    target: str,
    target_cases: frozenset[str],
    *,
    routing_changed: bool,
) -> Gates:
    left, right = (
        {(row.case_id, row.repeat): row for row in records} for records in (before, after)
    )
    if (
        not left
        or left.keys() != right.keys()
        or len(left) != len(before)
        or len(right) != len(after)
    ):
        raise ValueError("验证组必须包含完整且唯一的配对试验")
    origins: dict[str, str | None] = {}
    for key, row in left.items():
        other = right[key]
        if (
            row.seed_id != other.seed_id
            or origins.setdefault(row.case_id, row.seed_id) != row.seed_id
            or row.expected_skills != other.expected_skills
        ):
            raise ValueError("配对的种子和预期触发必须一致")
        for observation in (row, other):
            if (
                not observation.case_id
                or observation.repeat < 1
                or not math.isfinite(observation.score)
                or not 0 <= observation.probability <= 1
                or observation.soft is not None
                and not 0 <= observation.soft <= 1
            ):
                raise ValueError("验证组包含无效标识或分数")
    focused = [key for key in left if key[0] in target_cases]
    others = sorted(left.keys() - set(focused))
    if not focused or not others or {key[0] for key in focused} != target_cases:
        raise ValueError("验证组须覆盖全部目标题及其他题")

    component = target.removeprefix("component:")

    def affected(side: dict[tuple[str, int], Evaluation]) -> int:
        return len(
            {
                key[0]
                for key in focused
                if (
                    target in side[key].violations
                    if component == target
                    else component in side[key].weak_components
                )
            }
        )

    then, now = affected(left), affected(right)
    introduced_block = any(
        right[key].blocked
        and (not left[key].blocked or right[key].violations - left[key].violations)
        for key in focused
    )

    def trials(side: dict[tuple[str, int], Evaluation]) -> list[Trial]:
        return [
            Trial(row.case_id, row.repeat, not row.blocked, row.score, row.seed_id)
            for key in others
            for row in (side[key],)
        ]

    delta = compare(trials(left), trials(right))
    regression = delta.clusters >= 2 and delta.pass_rate.high >= 0 and delta.score.high >= 0

    probability_before, probability_after = (
        mean(row.probability for row in side) for side in (before, after)
    )
    eligible = [key for key in left if left[key].soft_applicable or right[key].soft_applicable]
    # Pair the same cases. Losing an eligible result contributes zero rather than dropping the case.
    complete_soft = all(
        not side[key].soft_applicable or side[key].soft is not None
        for side in (left, right)
        for key in eligible
    )
    before_mean, after_mean = (
        mean(side[key].soft or 0.0 for key in eligible) if eligible else 0.0
        for side in (left, right)
    )
    components = (
        complete_soft
        and probability_after >= probability_before
        and after_mean >= before_mean
        and (probability_after > probability_before or after_mean > before_mean)
    )

    def recall(rows: Sequence[Evaluation]) -> dict[str, tuple[int, int]]:
        names = {name for row in rows for name in row.expected_skills}
        return {
            name: (
                sum(name in row.loaded_skills for row in rows if name in row.expected_skills),
                sum(name in row.expected_skills for row in rows),
            )
            for name in names
        }

    before_recall, after_recall = recall(before), recall(after)
    coexistence = (
        not routing_changed
        or bool(before_recall)
        and all(
            name in after_recall and after_recall[name][0] * total >= count * after_recall[name][1]
            for name, (count, total) in before_recall.items()
        )
    )
    return Gates(
        then - now >= 2 and now * 2 <= then and not introduced_block,
        regression,
        components,
        coexistence,
        then,
        now,
        delta.pass_rate,
        delta.score,
        probability_before,
        probability_after,
        before_mean if eligible and complete_soft else None,
        after_mean if eligible and complete_soft else None,
    )


def _single_sentence(text: str) -> bool:
    return (
        "\n" not in text
        and "\r" not in text
        and len([part for part in _SENTENCE_END.split(text) if part.strip()]) == 1
    )


def evaluate_candidate(
    pool: Path,
    skills: SkillConfig,
    edit: GuardedEdit,
    target: str,
    target_cases: frozenset[str],
    baseline: Sequence[Evaluation],
    rerun: Callable[[Path], Sequence[Evaluation]],
) -> CandidateResult:
    if skills.variant != "full" or skills.disabled:
        raise ValueError("自进化的配对起点须启用全部 Skill")
    known = get_args(SkillName)
    existing = skills.candidate_names()
    texts = {name: skills.path(name).read_text(encoding="utf-8") for name in (*known, *existing)}
    if not _single_sentence(edit.new) or edit.new == edit.old:
        raise ValueError("候选只能改一句")
    routing_changed = edit.skill not in texts
    if edit.skill in texts:
        previous = texts[edit.skill]
        sentences = {part.strip() for part in _SENTENCE_END.split(previous)}
        if (
            not _single_sentence(edit.old)
            or edit.old not in sentences
            or previous.count(edit.old) != 1
        ):
            raise ValueError("原文中必须有唯一的一句可修改")
        if edit.trigger is not None:
            raise ValueError("改现有 Skill 时只能修改正文中的一句")
        updated = previous.replace(edit.old, edit.new, 1)
        routing_changed = (
            edit.skill in existing and previous.partition("\n")[0] != updated.partition("\n")[0]
        )
        texts[edit.skill] = updated
    else:
        if (
            edit.skill not in EXPERIMENTAL_SKILLS
            or edit.old
            or len(target_cases) < 2
            or not edit.uncovered_reason.strip()
            or not edit.trigger
            or len(edit.trigger) > 200
            or "\n" in edit.trigger
            or "\r" in edit.trigger
            or len(edit.trigger_examples) != 3
            or len(set(edit.trigger_examples)) != 3
            or any(not example.strip() for example in edit.trigger_examples)
        ):
            raise ValueError("新 Skill 需要重复失败、现有条目无法覆盖及正例、反例、边界三条用例")
        texts[edit.skill] = f"触发：{edit.trigger}\n\n{edit.new}\n"

    baseline_data = json.dumps(
        [asdict(row) for row in sorted(baseline, key=lambda row: (row.case_id, row.repeat))],
        default=sorted,
        sort_keys=True,
    )
    evidence_key = hashlib.sha256(baseline_data.encode()).hexdigest()
    cohort = pool / evidence_key
    cohort.mkdir(parents=True, exist_ok=True)
    directory = Path(mkdtemp(prefix="skill-", dir=cohort))
    for name, text in texts.items():
        (directory / f"{name}.md").write_text(text, encoding="utf-8")

    candidate = rerun(directory)
    gates = assess(baseline, candidate, target, target_cases, routing_changed=routing_changed)
    (directory / "pairs.json").write_text(
        '{"baseline":'
        + baseline_data
        + ',"candidate":'
        + json.dumps([asdict(row) for row in candidate], default=sorted)
        + "}\n",
        encoding="utf-8",
    )
    before_by_key = {(row.case_id, row.repeat): row for row in baseline}
    regressed = sorted(
        {
            row.case_id
            for row in candidate
            if row.case_id not in target_cases
            and (
                row.score < before_by_key[row.case_id, row.repeat].score
                or row.blocked
                and not before_by_key[row.case_id, row.repeat].blocked
            )
        }
    )
    review = directory / "review.md"
    before_score, candidate_score = (
        mean(row.score for row in side) for side in (baseline, candidate)
    )
    review.write_text(
        f"# {edit.skill}\n\n目标 `{target}`，固定验证组 {len(target_cases)} 道目标题。\n\n"
        f"- 原句为「{edit.old or '新条目'}」。候选句为「{edit.new}」。\n"
        f"- 目标违规从 {gates.target_before} 道变为 {gates.target_after} 道。"
        f"平均期望分从 {before_score:.4f} 变为 {candidate_score:.4f} 日元。\n"
        f"- 其他题无拦截比例差为 {gates.other_pass_rate.mean:+.1%}，"
        f"95% 区间 {gates.other_pass_rate.low:+.1%} 至 {gates.other_pass_rate.high:+.1%}。"
        f"期望分差为 {gates.other_score.mean:+.4f}，"
        f"95% 区间 {gates.other_score.low:+.4f} 至 {gates.other_score.high:+.4f} 日元。\n"
        f"- 其他题中分数下降或新增拦截的题目为 {', '.join(regressed) or '无'}。"
        "逐题结果保存在 pairs.json。\n"
        f"- 下单概率从 {gates.probability_before:.4%} 变为 {gates.probability_after:.4%}。"
        f"可用软项均分从 {gates.soft_before} 变为 {gates.soft_after}。\n"
        f"- 目标闸 {gates.target}、回归闸 {gates.regression}、"
        f"分量闸 {gates.components}、共存闸 {gates.coexistence}。"
        f"{'可送人工审核' if gates.passed else '候选未通过四道闸'}。\n"
        + (
            "\n## 触发用例\n\n" + "\n".join(f"- {example}" for example in edit.trigger_examples)
            if edit.trigger_examples
            else ""
        ),
        encoding="utf-8",
    )
    with NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as temporary:
        json.dump(
            {"target": target, "score": candidate_score, "passed": gates.passed},
            temporary,
            ensure_ascii=False,
        )
    Path(temporary.name).replace(directory / "result.json")
    confirmed: list[tuple[float, Path]] = []
    for path in cohort.glob("skill-*/result.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["target"] == target and data["passed"]:
            confirmed.append((data["score"], path.parent))
    best = max(confirmed, key=lambda entry: (entry[0], str(entry[1])))[1] if confirmed else None
    return CandidateResult(directory, review, gates, best)

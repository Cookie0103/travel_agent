"""只在隔离评测库启用 Skill 消融与只读候选覆盖。"""

import hashlib
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

from backend.adapters.evaluation_faults import is_eval_database
from backend.domain.tool_facts import (
    EXPERIMENTAL_SKILLS,
    EvaluationSkillName,
    ExperimentSkillName,
    SkillName,
)

SkillVariant = Literal["full", "no_skills"]
BUILTIN_SKILLS = Path(__file__).resolve().parent / "skills"


class SkillConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    variant: SkillVariant = "full"
    disabled: SkillName | None = None
    directory: Path | None = None

    def authorize(self, *, evaluation: bool, dsn: str) -> None:
        if self == SkillConfig():
            return
        if not evaluation or not is_eval_database(dsn):
            raise ValueError("Skill 变体和候选目录只允许专用本地评测库")
        if self.variant == "no_skills" and (self.disabled or self.directory):
            raise ValueError("关闭全部 Skill 时不能再指定单个关闭项或候选目录")
        if self.directory is not None and not self.directory.is_dir():
            raise ValueError("Skill 候选目录不存在")

    def enabled(self, name: EvaluationSkillName) -> bool:
        if name in EXPERIMENTAL_SKILLS:
            return name in self.candidate_names()
        return self.variant != "no_skills" and self.disabled != name

    def candidate_names(self) -> tuple[ExperimentSkillName, ...]:
        if self.variant != "full" or self.directory is None:
            return ()
        return tuple(
            name for name in EXPERIMENTAL_SKILLS if (self.directory / (name + ".md")).is_file()
        )

    def candidate_trigger(self, name: ExperimentSkillName) -> str:
        first_line = self.path(name).read_text(encoding="utf-8").partition("\n")[0]
        return first_line.removeprefix("触发：")[:200]

    def path(self, name: EvaluationSkillName) -> Path:
        filename = name + ".md"
        if self.directory is not None:
            root = self.directory.resolve()
            candidate = root / filename
            if candidate.is_symlink() or candidate.exists():
                target = candidate.resolve()
                if target.parent != root or not target.is_file():
                    raise ValueError("Skill 候选必须是该目录内的文本文件")
                return target
        if name in EXPERIMENTAL_SKILLS:
            raise ValueError("评测候选 Skill 文件不存在")
        return BUILTIN_SKILLS / filename

    def versions(self) -> dict[str, str]:
        if self.directory is None:
            return {}
        names = (*get_args(SkillName), *self.candidate_names())
        return {
            name: hashlib.sha256(self.path(name).read_bytes()).hexdigest()
            for name in names
            if self.enabled(name)
        }

"""只在隔离评测库启用 Skill 消融与只读候选覆盖。"""

import hashlib
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

from backend.adapters.evaluation_faults import is_eval_database
from backend.domain.tool_facts import SkillName

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

    def enabled(self, name: SkillName) -> bool:
        return self.variant != "no_skills" and self.disabled != name

    def path(self, name: SkillName) -> Path:
        filename = name + ".md"
        if self.directory is not None:
            root = self.directory.resolve()
            candidate = root / filename
            if candidate.is_symlink() or candidate.exists():
                target = candidate.resolve()
                if target.parent != root or not target.is_file():
                    raise ValueError("Skill 候选必须是该目录内的文本文件")
                return target
        return BUILTIN_SKILLS / filename

    def versions(self) -> dict[str, str]:
        if self.directory is None:
            return {}
        return {
            name: hashlib.sha256(self.path(name).read_bytes()).hexdigest()
            for name in get_args(SkillName)
            if self.enabled(name)
        }

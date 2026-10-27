"""仅active长期事实的有引用画像；自由文本为数据，服务器只验证来源与有界输出。"""

import re
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ProfileGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sentences: tuple[str, ...] = Field(max_length=6)


class UserProfileView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str | None = None
    cited_fact_ids: tuple[UUID, ...] = ()
    created_at: AwareDatetime | None = None
    can_update: bool = False


def supported_profile(
    output: ProfileGeneration, active_ids: set[UUID]
) -> tuple[str, tuple[UUID, ...]]:
    valid: list[str] = []
    cited: set[UUID] = set()
    for sentence in output.sentences:
        ids = re.findall(r"\[fact:([0-9a-fA-F-]{36})\]", sentence)
        try:
            refs = {UUID(value) for value in ids}
        except ValueError:
            continue
        if not refs or not refs <= active_ids:
            continue
        # 其它残缺引用也使整句无效，不能留一个合法引用蒙混过关。
        plain = re.sub(r"\[fact:[0-9a-fA-F-]{36}\]", "", sentence)
        if "[fact:" in plain or not plain.strip():
            continue
        if len([part for part in re.split(r"[。！？.!?]+", plain) if part.strip()]) > 1:
            continue
        if len("\n".join([*valid, sentence])) > 600:
            continue
        valid.append(sentence.strip())
        cited.update(refs)
    return "\n".join(valid), tuple(sorted(cited, key=str))

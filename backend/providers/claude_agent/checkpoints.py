"""私有SDK续接指针；只接受完整成功轮次，损坏/版本/条件变化退回业务快照。"""

import hashlib
from pathlib import Path
from uuid import UUID

from claude_agent_sdk import get_session_info
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.domain.execution import RunContext, RuntimeIdentity, SessionReference


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reference: SessionReference
    request_revision: int = Field(ge=0)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class Checkpoints:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "checkpoint.json"

    def _digest(self, sdk_session_id: str) -> str | None:
        identity = str(UUID(sdk_session_id))
        # SDK公共接口核对当前隔离目录，文件只读用于完整性指纹，不重写transcript。
        if get_session_info(identity, directory=str(self.directory)) is None:
            return None
        files = list((self.directory / "config" / "projects").glob(f"*/{identity}.jsonl"))
        if len(files) != 1 or files[0].is_symlink() or files[0].stat().st_size > 16 * 1024 * 1024:
            return None
        return hashlib.sha256(files[0].read_bytes()).hexdigest()

    def load(
        self, context: RunContext, identity: RuntimeIdentity, revision: int
    ) -> SessionReference | None:
        try:
            if self.path.stat().st_size > 64 * 1024:
                return None
            saved = Checkpoint.model_validate_json(self.path.read_bytes())
            reference = saved.reference
            if (
                (reference.context.user_id, reference.context.session_id)
                != (context.user_id, context.session_id)
                or reference.identity != identity
                or saved.request_revision != revision
                or self._digest(reference.sdk_session_id) != saved.digest
            ):
                return None
            return reference
        except (OSError, ValidationError, ValueError):
            return None

    def invalidate(self) -> None:
        # 执行前先撤掉旧指针；崩溃不能把旧完整轮次当成本轮DB写入的原子断点。
        self.path.unlink(missing_ok=True)

    def save(self, reference: SessionReference, revision: int) -> bool:
        try:
            digest = self._digest(reference.sdk_session_id)
            if digest is None:
                return False
            saved = Checkpoint(reference=reference, request_revision=revision, digest=digest)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(saved.model_dump_json() + "\n", encoding="utf-8", newline="\n")
            temporary.replace(self.path)
            return True
        except (OSError, ValueError):
            return False

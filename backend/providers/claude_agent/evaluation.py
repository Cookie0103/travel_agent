"""仅供评测的单因素配置；工具集合在parent守卫与SDK worker保持同一来源。"""

from typing import Literal, get_args

from backend.tools.contracts import ToolDefinition
from backend.tools.search import DEFINITIONS as SEARCH_DEFINITIONS
from backend.tools.travel import DEFINITIONS as TRAVEL_DEFINITIONS
from backend.tools.workflow import WorkflowName

type EvaluationVariant = Literal[
    "full", "no_tools", "no_skills", "no_preferences", "no_repairs", "no_compaction"
]


def validate_variant(
    variant: EvaluationVariant,
    *,
    database: bool,
    workflow: WorkflowName | None,
    judge: bool = False,
) -> None:
    if variant not in get_args(EvaluationVariant.__value__):
        raise ValueError("未知评测配置")
    if variant == "no_compaction":
        raise ValueError("锁定SDK尚未核验可靠的压缩关闭能力")
    if variant != "full" and (workflow or judge):
        raise ValueError("单因素对照不能混用固定workflow或语气评审")
    if variant not in {"full", "no_tools"} and not database:
        raise ValueError("业务单因素对照需要数据库")


def evaluation_definitions(
    variant: EvaluationVariant, *, database: bool
) -> tuple[ToolDefinition, ...]:
    if variant == "no_tools":
        return ()
    definitions = TRAVEL_DEFINITIONS if database else SEARCH_DEFINITIONS
    return tuple(d for d in definitions if variant != "no_skills" or d.name != "load_skill")

"""仅供评测的基线/单因素配置；parent守卫与SDK worker共享工具集合。"""

from typing import Literal, get_args

from backend.tools.contracts import ToolDefinition
from backend.tools.search import DEFINITIONS as SEARCH_DEFINITIONS
from backend.tools.travel import DEFINITIONS as TRAVEL_DEFINITIONS
from backend.tools.workflow import WorkflowName

type EvaluationVariant = Literal[
    "full", "no_tools", "no_skills", "no_preferences", "no_repairs", "no_compaction", "baseline_b2"
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
    if variant != "full" and (workflow or judge):
        raise ValueError("评测对照不能混用固定workflow或语气评审")
    if variant not in {"full", "no_tools"} and not database:
        raise ValueError("业务评测对照需要数据库")


def evaluation_definitions(
    variant: EvaluationVariant, *, database: bool
) -> tuple[ToolDefinition, ...]:
    if variant == "no_tools":
        return ()
    definitions = TRAVEL_DEFINITIONS if database else SEARCH_DEFINITIONS
    return tuple(d for d in definitions if variant != "no_skills" or d.name != "load_skill")


def evaluation_metadata(
    variant: EvaluationVariant,
    *,
    live: bool,
    database: bool,
    workflow: WorkflowName | None,
) -> dict[str, object]:
    """运行manifest和离线比较共用声明，避免实验组定义漂移。"""
    validate_variant(variant, database=database, workflow=workflow)
    return {
        "evaluation_variant": variant,
        "comparison_group": "not_applicable_fixture"
        if not live
        else "search_only"
        if not database
        else "B1"
        if workflow
        else {"full": "B3", "no_tools": "B0", "baseline_b2": "B2"}.get(variant, "single_factor"),
        "automatic_compaction": "verified_versions_env"
        if variant in {"no_compaction", "baseline_b2"}
        else "sdk_default"
        if live
        else "not_applicable_fixture",
        "sdk_resume_enabled": live and database and variant == "full",
        "workflow": workflow or "autonomous",
    }

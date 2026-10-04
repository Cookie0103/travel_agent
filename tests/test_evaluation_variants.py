"""plan05对照：配置不能混因子、不能用fixture模拟效果、不能收费后才发现非法。"""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext
from backend.providers.claude_agent.evaluation import (
    EvaluationVariant,
    evaluation_definitions,
    validate_variant,
)
from backend.providers.claude_agent.live import run_live
from backend.providers.claude_agent.worker import run as run_worker
from backend.providers.probe.settings import ProbeError
from backend.tools.travel import DEFINITIONS
from eval.run import main, run_cases


def test_variants_reuse_original_definitions_and_remove_only_declared_skill() -> None:
    assert evaluation_definitions("full", database=True) == DEFINITIONS
    no_skills = evaluation_definitions("no_skills", database=True)
    assert no_skills == tuple(d for d in DEFINITIONS if d.name != "load_skill")
    for variant in ("no_preferences", "no_repairs", "no_compaction", "baseline_b2"):
        assert evaluation_definitions(variant, database=True) == DEFINITIONS
    assert evaluation_definitions("no_tools", database=True) == ()
    assert evaluation_definitions("no_tools", database=False) == ()


@pytest.mark.parametrize("variant", ["unknown", ""])
def test_unsupported_variant_is_rejected_before_budget_or_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: EvaluationVariant
) -> None:
    def forbidden(*args: object) -> None:
        raise AssertionError("非法配置不能读取模型收费配置")

    monkeypatch.setattr("backend.providers.claude_agent.live.load_runtime_settings", forbidden)
    with pytest.raises(ProbeError, match="配置|压缩"):
        run_live("京都", RunContext(uuid4()), tmp_path, evaluation_variant=variant)
    assert not (tmp_path / ".cache").exists()


def test_one_factor_variants_require_database_and_reject_workflow_or_judge() -> None:
    with pytest.raises(ValueError):
        validate_variant("no_preferences", database=False, workflow=None)
    for variant in (
        "no_tools",
        "no_skills",
        "no_preferences",
        "no_repairs",
        "no_compaction",
        "baseline_b2",
    ):
        with pytest.raises(ValueError):
            validate_variant(variant, database=True, workflow="search")
        with pytest.raises(ValueError):
            validate_variant(variant, database=True, workflow=None, judge=True)


@pytest.mark.parametrize(
    "extra",
    [
        {"evaluation_variant": "unknown"},
        {"evaluation_variant": "no_compaction"},
        {"evaluation_variant": "baseline_b2"},
        {"evaluation_variant": "no_preferences"},
        {"evaluation_variant": "no_tools", "prompts": ["one", "two"]},
        {"evaluation_variant": "no_tools", "workflow": "search"},
        {"evaluation_variant": "no_tools", "persona_judge": True},
    ],
)
def test_worker_invalid_combination_never_starts_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: dict[str, object]
) -> None:
    monkeypatch.setenv("ANTHROPIC_MODEL", "deepseek-flash")

    async def forbidden(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("非法评测配置不能启动SDK")

    monkeypatch.setattr("backend.providers.claude_agent.worker.run_prompts", forbidden)
    result = asyncio.run(
        run_worker(
            {
                "user_id": str(uuid4()),
                "session_id": str(uuid4()),
                "run_id": str(uuid4()),
                "prompts": ["one"],
                "cli_version": "2.1.114",
                **extra,
            },
            tmp_path / "unused",
        )
    )
    assert result == {"status": "error", "code": "validation"}


@pytest.mark.asyncio
async def test_offline_fixture_cannot_claim_variant_effect(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="实际SDK"):
        await run_cases([], tmp_path / "output", variant="no_tools")
    assert not (tmp_path / "output").exists()


def test_eval_cli_compaction_or_offline_variant_stops_before_database_or_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("非法对照不能创建库或预检费用")

    monkeypatch.setattr("eval.run.check_evaluation_size", forbidden)
    monkeypatch.setattr("eval.run.temporary_database", forbidden)
    for arguments in (
        ["--variant", "no_compaction", "--database"],
        ["--variant", "no_tools", "--database"],
        ["--variant", "no_skills", "--database", "--live", "--workflow", "search"],
    ):
        monkeypatch.setattr("sys.argv", ["eval.run", *arguments])
        assert main() == 1

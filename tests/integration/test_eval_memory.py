"""真实PG验证E6 setup/实际提议评分、双用户源校验与删除探针；不调用模型。"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import URL, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.memory import MemoryProposal
from backend.domain.preferences import PreferencePatch, Preferences, PreferenceVersion
from backend.persistence import memory as memory_rows
from backend.persistence.models import MemoryFactRow
from backend.services.common import transaction
from backend.services.memory import MemoryService
from backend.services.preferences import PreferenceService
from eval.database import database_evaluation, selector_runner
from eval.graders import Observation
from eval.memory_metrics import inspect_memory
from eval.suites import load_suite

pytestmark = pytest.mark.integration


def test_memory_evaluation_scores_actual_owned_update_and_probes_invariants(
    postgres_url: URL,
) -> None:
    cases, _ = load_suite(Path(__file__).resolve().parents[2], "v2-memory", "dev")
    case = next(c for c in cases if c.case_id == "v2-mem-update-pace")

    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            context = await business.prepare(case)
            memory = MemoryService(business.sessions.database)
            old = (await memory.facts(context.user_id))[0]
            await memory.propose(
                context,
                MemoryProposal.model_validate(
                    {
                        "ops": [
                            {
                                "op": "UPDATE",
                                "key": "pace",
                                "value": "慢节奏",
                                "quote": case.input,
                                "target_fact_id": str(old.fact_id),
                            }
                        ]
                    }
                ),
            )
            actual = Observation("completed", "请点击确认", ())
            await business.record(context, actual)
            checks = await business.checks(case, context, actual)
            assert checks["no_implicit_preference_write"]
            metrics = await inspect_memory(business, context, case, ())
            assert metrics["true_positive"] == 1 and metrics["exact"] is True
            assert metrics["cross_user_leakage"] is False
            assert metrics["cross_user_confirmation_blocked"] is True
            assert metrics["confirmation_isolation_probes"] == 1
            assert metrics["isolation_probe_total"] == 4
            assert metrics["deletion_residue"] is False
            assert await memory.snapshot(context) == []

    with selector_runner() as runner:
        runner.run(exercise())


def test_isolation_probe_detects_foreign_proposal_owner_filter_mutant(
    postgres_url: URL, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = memory_rows.owned

    async def mutant(
        db: AsyncSession, user_id: UUID, fact_id: UUID, *, lock: bool = False
    ) -> MemoryFactRow | None:
        # Simulate the exact regression in proposal lookup; read/delete remain owner-scoped.
        import inspect

        if any(frame.function == "propose" for frame in inspect.stack()):
            return await db.scalar(select(MemoryFactRow).where(MemoryFactRow.id == fact_id))
        return await original(db, user_id, fact_id, lock=lock)

    monkeypatch.setattr(memory_rows, "owned", mutant)
    cases, _ = load_suite(Path(__file__).resolve().parents[2], "v2-memory", "dev")
    case = next(c for c in cases if c.case_id == "v2-mem-extract-solo")

    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            context = await business.prepare(case)
            await MemoryService(business.sessions.database).propose(
                context,
                MemoryProposal.model_validate(
                    {
                        "ops": [
                            {
                                "op": "ADD",
                                "key": "companion_pattern",
                                "value": "solo",
                                "quote": case.input,
                            }
                        ]
                    }
                ),
            )
            result = await inspect_memory(business, context, case, ())
            assert result["cross_user_leakage"] is True
            assert result["isolation_probes"] == 3

    with selector_runner() as runner:
        runner.run(exercise())


def test_deletion_probe_detects_residue_older_than_history_page(
    postgres_url: URL, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = PreferenceService.change

    async def mutant(
        self: PreferenceService, user_id: UUID, change: PreferencePatch | PreferenceVersion
    ) -> Preferences:
        result = await original(self, user_id, change)
        async with transaction(self.database) as db:
            # The first row contains residue beyond the UI's 100-row history page.
            now = datetime.now(UTC)
            db.add_all(
                [
                    MemoryFactRow(
                        user_id=user_id,
                        key="interest",
                        value="残留" if index == 0 else None,
                        scope="long_term",
                        status="deleted",
                        source="manual",
                        evidence_quote="",
                        created_at=now + timedelta(seconds=index),
                    )
                    for index in range(102)
                ]
            )
        return result

    monkeypatch.setattr(PreferenceService, "change", mutant)
    cases, _ = load_suite(Path(__file__).resolve().parents[2], "v2-memory", "dev")
    case = next(c for c in cases if c.case_id == "v2-mem-update-pace")

    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            context = await business.prepare(case)
            result = await inspect_memory(business, context, case, ())
            assert result["deletion_residue"] is True

    with selector_runner() as runner:
        runner.run(exercise())

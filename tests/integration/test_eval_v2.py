"""V2终态与选择必须在真实PG评测run中，不依赖模型自述。"""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import URL

from backend.persistence.models import TaskRunRow
from eval.cases import Case
from eval.database import database_evaluation
from eval.run import run_cases

pytestmark = pytest.mark.integration


def test_v2_eval_creates_owned_run_and_checks_predeclared_state(
    postgres_url: URL, tmp_path: Path
) -> None:
    case = Case(
        case_id="v2-state-control",
        source="self-authored facility control",
        adaptation="no quality claim",
        input="京都景点",
        allowed_tools=["search_places", "search_content"],
        required_tools=["search_places"],
        should_have_results=True,
        initial_state={"request": {"city": "京都", "adults": 2}},
        expected_state={"request": {"city": "京都"}, "bookings": [], "saved_version": 0},
    )

    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            context = await business.prepare(case)
            async with business.sessions.database.sessions() as db:
                row = await db.get(TaskRunRow, context.run_id)
                assert row and row.status == "running" and row.prompt == case.input
            await run_cases([case], tmp_path / "run", business=business)
            row = json.loads((tmp_path / "run/results.jsonl").read_text())
            assert row["checks"]["expected_state"] is True
            assert "process_metrics" in row

    with asyncio.Runner() as runner:
        runner.run(exercise())

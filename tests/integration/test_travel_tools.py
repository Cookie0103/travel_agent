"""R01/R03/R15/R16：真实数据库旅行工具的参数、归属、串行与受控Skill边界。"""

import asyncio
from uuid import UUID, uuid4

import pytest

from backend.domain.execution import RunContext
from backend.persistence.catalog import import_catalog
from backend.services.common import transaction
from backend.services.travel import TravelService
from backend.tools.travel import DEFINITIONS, SCHEMAS, TravelToolExecutor
from data.import_catalog import load_snapshot
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def test_catalog_tools_return_snapshot_with_owned_evidence(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R03/R05：快照结果与证据配对，不能沿用fixture标签或接受伪造地点ID。"""
    runner, service, context = travel_setup

    async def exercise() -> None:
        async with transaction(service.database) as db:
            await import_catalog(db, load_snapshot())
        executor = TravelToolExecutor(service)
        result = await executor.execute(
            context, "search_places", {"city": "京都", "query": "清水寺", "limit": 1}
        )
        assert result.code is None and result.data_mode == "snapshot" and not result.empty
        records = await service.resolve_evidence(
            context, [UUID(key) for key in result.evidence_ids]
        )
        assert len(records) == 1 and records[0].status == "verified"
        facts = await executor.execute(
            context, "get_place_facts", {"entity_id": records[0].entity_id}
        )
        assert facts.code is None and facts.evidence_ids
        missing = await executor.execute(context, "get_place_facts", {"entity_id": "fake"})
        assert missing.code == "blocked"
        empty = await executor.execute(context, "search_content", {"city": "大阪"})
        assert empty.empty and empty.code is None and empty.data_mode == "snapshot"

    runner.run(exercise())


def test_tool_arguments_and_registry_cannot_grant_write_permissions(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R01/R15/R16：参数不能注入身份或权限；文本声称确认也没有正式写工具。"""
    runner, service, context = travel_setup

    async def exercise() -> None:
        assert {d.name for d in DEFINITIONS} == SCHEMAS.keys()
        assert all(d.schema == SCHEMAS[d.name].model_json_schema() for d in DEFINITIONS)
        executor = TravelToolExecutor(service)
        forbidden = await executor.execute(context, "confirm_booking", {"confirmed": True})
        assert forbidden.code == "blocked"
        injected = await executor.execute(
            context, "search_places", {"city": "京都", "user_id": str(uuid4())}
        )
        assert injected.code == "validation"
        escaped = await executor.execute(context, "load_skill", {"name": "../../.env"})
        assert escaped.code == "validation"
        skill = await executor.execute(context, "load_skill", {"name": "hotel-comparison"})
        again = await executor.execute(context, "load_skill", {"name": "hotel-comparison"})
        assert "instructions" in skill.data and again.data["already_loaded"] is True
        assert "instructions" not in again.data
        other_run = await executor.execute(
            RunContext(context.user_id, context.session_id),
            "load_skill",
            {"name": "hotel-comparison"},
        )
        assert other_run.code == "blocked"

    runner.run(exercise())


def test_tool_calls_are_serialized_and_failures_count_toward_limit(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R01/R04：同轮写操作排他；并行提出的同revision更新不能交错覆盖。"""
    runner, service, context = travel_setup

    async def exercise() -> None:
        executor = TravelToolExecutor(service, max_calls=3)
        results = await asyncio.gather(
            *(
                executor.execute(
                    context,
                    "update_travel_request",
                    {"expected_revision": 1, "set": {"adults": adults}},
                )
                for adults in (3, 4)
            )
        )
        assert sum(r.code is None for r in results) == 1
        assert sum(r.code == "conflict" for r in results) == 1
        invalid = await executor.execute(context, "search_places", {})
        assert invalid.code == "validation"
        exhausted = await executor.execute(context, "load_skill", {"name": "hotel-comparison"})
        assert exhausted.code == "blocked" and executor.calls == 3

    runner.run(exercise())

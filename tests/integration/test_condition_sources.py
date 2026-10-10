"""U1：来源优先、来源-only不增revision、明确与模糊操作不可互用，真实PG。"""

import asyncio

import pytest

from backend.domain.execution import RunContext
from backend.domain.travel_request import ConversationRequestPatch, RequestPatch, legacy_request
from backend.persistence import operations
from backend.persistence.models import TravelRequestRow
from backend.services.common import transaction
from backend.services.travel import TravelService
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def test_form_value_is_protected_but_explicit_same_patch_can_update(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, service, context = travel_setup

    async def exercise() -> None:
        patch = RequestPatch.model_validate({"expected_revision": 1, "set": {"adults": 3}})
        vague = await service.patch_request(context, patch, source="conversation")
        assert vague.request.adults == 2 and vague.request.revision == 1
        assert vague.skipped_fields == ("adults",) and not vague.changed_fields
        explicit = await service.patch_request(
            context, patch, source="conversation", explicit_fields=("adults",)
        )
        assert explicit.request.adults == 3 and explicit.request.revision == 2
        assert explicit.changed_fields == ("adults",) and not explicit.skipped_fields
        view = await service.get_request_view(context)
        assert view.field_sources["adults"] == "conversation"
        assert view.field_sources["city"] == "user_form"
        assert (
            await service.patch_request(
                context, patch, source="conversation", explicit_fields=("adults",)
            )
        ).field_sources == view.field_sources

    runner.run(exercise())


def test_legacy_tool_patch_replay_uses_actual_old_key_without_inventing_source(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, service, context = travel_setup

    async def exercise() -> None:
        old_patch = RequestPatch.model_validate({"expected_revision": 0, "set": {"adults": 2}})
        current = await service.get_request(context)
        async with transaction(service.database) as db:
            row = await db.get(TravelRequestRow, context.session_id)
            assert row
            row.request_details = None
            operations.save(
                db,
                context.session_id,
                "update_travel_request",
                operations.key(old_patch),
                {"request": legacy_request(current), "changed_fields": ["adults"]},
            )
        new_tool_patch = ConversationRequestPatch.model_validate(
            {"expected_revision": 0, "set": {"adults": 2}}
        )
        replay = await service.patch_request(context, new_tool_patch, source="conversation")
        assert replay.request.revision == 1 and replay.request.adults == 2
        assert set(replay.field_sources.values()) == {"none"}

    runner.run(exercise())


def test_source_only_change_replay_clear_and_old_writer_keep_facts(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, service, context = travel_setup

    async def exercise() -> None:
        budget = RequestPatch.model_validate({"expected_revision": 1, "set": {"budget": "60000"}})
        conversation = await service.patch_request(
            context, budget, source="conversation", explicit_fields=("budget",)
        )
        assert conversation.request.revision == 2
        assert conversation.field_sources["budget"] == "conversation"
        same = RequestPatch.model_validate({"expected_revision": 2, "set": {"budget": "60000.00"}})
        form = await service.patch_request(context, same)
        assert not form.changed_fields and form.request.revision == 2
        assert form.field_sources["budget"] == "user_form"
        replay = await service.patch_request(
            context, budget, source="conversation", explicit_fields=("budget",)
        )
        assert replay.field_sources["budget"] == "user_form"
        cleared = await service.patch_request(
            context, RequestPatch(expected_revision=2, clear=("budget",))
        )
        assert cleared.request.budget is None and cleared.request.revision == 3
        assert cleared.field_sources["budget"] == "none"
        async with transaction(service.database) as db:
            row = await db.get(TravelRequestRow, context.session_id)
            assert row
            row.conditions = {**row.conditions, "adults": 4}
            row.revision = 4
        view = await service.get_request_view(context)
        assert view.adults == 4 and set(view.field_sources.values()) == {"none"}

    runner.run(exercise())

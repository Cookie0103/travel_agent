"""R02/R12：真实PG、实际退出进程、业务写入重放和启动只读恢复。"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL, func, select

from backend.api.app import create_app
from backend.domain.booking import HoldHotelInput
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeOutcome
from backend.domain.hotels import HotelOffer
from backend.domain.plans import StageInput
from backend.domain.travel_request import RequestPatch
from backend.persistence import runs
from backend.persistence.database import Database
from backend.persistence.models import (
    BusinessOperationRow,
    EvidenceRow,
    PlanDraftRow,
    SupplierHoldRow,
    SupplierOrderRow,
)
from backend.services.bookings import BookingService
from backend.services.common import ServiceError, transaction
from backend.services.hotels import HotelService
from backend.services.plans import PlanService
from backend.services.runs import MessageInput, RunService
from backend.services.sessions import SessionService
from backend.services.travel import TravelService
from mock_supplier.service import SupplierService
from tests.fakes import FakeRuntime
from tests.integration.test_planning import destinations, proposal
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def test_database_outage_during_startup_retries_recovery_before_concurrent_new_messages(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    with socket.socket() as closed_port:
        closed_port.bind(("127.0.0.1", 0))
        unavailable = Database(travel.database.engine.url.set(port=closed_port.getsockname()[1]))
        runtime = FakeRuntime(RuntimeOutcome(text="new", sdk_session_id="fake"))
        service = RunService(unavailable, runtime_factory=lambda executor: runtime)

        async def exercise() -> None:
            await service.initialize()
            assert service.recovery_pending and runtime.resumed == []
            with pytest.raises(ServiceError, match="恢复核对"):
                await service.submit(
                    context.user_id,
                    context.session_id,
                    MessageInput(client_message_id=uuid4(), text="继续"),
                )
            async with transaction(travel.database) as db:
                interrupted = await runs.create(
                    db, context.user_id, context.session_id, uuid4(), "旧执行", "offline"
                )
                previous_id = interrupted.id
            service.database = travel.database
            message = MessageInput(client_message_id=uuid4(), text="新执行")
            one, two = await asyncio.gather(
                *(service.submit(context.user_id, context.session_id, message) for _ in range(2))
            )
            assert one.run_id == two.run_id and not service.recovery_pending
            assert (await service.get(context.user_id, previous_id)).status == "partial"
            await service.close()
            assert runtime.resumed == [None]
            assert len(await service.events(context.user_id, previous_id, 0)) == 1
            await unavailable.close()

        runner.run(exercise())


def commit_then_kill(
    travel: TravelService, context: RunContext, mode: str, arguments: dict[str, object]
) -> None:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    with subprocess.Popen(
        [sys.executable, "-m", "tests.integration.recovery_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    ) as process:
        assert process.stdin and process.stdout
        process.stdin.write(
            json.dumps(
                {
                    "dsn": travel.database.engine.url.render_as_string(hide_password=False),
                    "user_id": str(context.user_id),
                    "session_id": str(context.session_id),
                    "mode": mode,
                    "arguments": arguments,
                }
            )
            + "\n"
        )
        process.stdin.flush()
        try:
            with ThreadPoolExecutor(max_workers=1) as reader:
                marker = reader.submit(process.stdout.readline)
                try:
                    assert marker.result(timeout=10).strip() == "committed"
                finally:
                    process.kill()
        finally:
            process.kill() if process.poll() is None else None
            process.communicate(timeout=5)
        assert process.returncode != 0


def test_process_killed_after_patch_commit_replays_same_result_and_rejects_later_revision(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    patch = RequestPatch.model_validate({"expected_revision": 1, "set": {"rooms": 2}})
    commit_then_kill(
        travel, context, "patch", patch.model_dump(mode="json", by_alias=True, exclude_unset=True)
    )

    async def exercise() -> None:
        recovered = replace(context, run_id=uuid4())
        result = await travel.patch_request(recovered, patch)
        assert result.request.revision == 2 and result.request.rooms == 2
        equivalent = RequestPatch.model_validate(
            {"expected_revision": 1, "set": {"rooms": 2}, "clear": []}
        )
        assert await travel.patch_request(recovered, equivalent) == result
        assert await TravelService(travel.database).patch_request(recovered, patch) == result
        await travel.patch_request(
            context, RequestPatch.model_validate({"expected_revision": 2, "set": {"adults": 3}})
        )
        with pytest.raises(ServiceError, match="条件已变化"):
            await travel.patch_request(recovered, patch)
        assert (await travel.get_request(context)).revision == 3

    runner.run(exercise())


def test_process_killed_after_stage_commit_new_executor_keeps_draft_and_item_ids(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    first, _ = runner.run(destinations(travel, context))
    body = StageInput.model_validate(
        {"change": {"kind": "initial", "proposal": proposal(first).model_dump(mode="json")}}
    )
    commit_then_kill(travel, context, "stage", body.model_dump(mode="json"))

    async def exercise() -> None:
        new_context = replace(context, run_id=uuid4())
        one, two = await asyncio.gather(
            *(PlanService(travel).stage(new_context, body) for _ in range(2))
        )
        alternative = body.model_dump(mode="json")
        alternative["change"]["proposal"].pop("hotel_evidence_id")
        assert (
            await PlanService(travel).stage(new_context, StageInput.model_validate(alternative))
            == one
        )
        assert one == two and one.content.items[0].item_id == two.content.items[0].item_id
        async with transaction(travel.database) as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(PlanDraftRow)
                    .where(PlanDraftRow.session_id == context.session_id)
                )
                == 1
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(BusinessOperationRow)
                    .where(
                        BusinessOperationRow.session_id == context.session_id,
                        BusinessOperationRow.name == "stage_plan",
                    )
                )
                == 1
            )
        with pytest.raises(ServiceError, match="会话不存在"):
            await PlanService(travel).stage(replace(context, user_id=uuid4()), body)

    runner.run(exercise())


def test_stage_and_operation_record_roll_back_together_on_validation_failure(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        first, _ = await destinations(travel, context)
        body = StageInput.model_validate(
            {"change": {"kind": "initial", "proposal": proposal(first).model_dump(mode="json")}}
        )

        def fail(candidate: object) -> None:
            raise ServiceError(503, "unavailable", "故障注入：校验失败")

        with pytest.raises(ServiceError, match="校验失败"):
            await PlanService(travel).stage(context, body, before_validate=fail)
        async with transaction(travel.database) as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(PlanDraftRow)
                    .where(PlanDraftRow.session_id == context.session_id)
                )
                == 0
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(BusinessOperationRow)
                    .where(
                        BusinessOperationRow.session_id == context.session_id,
                        BusinessOperationRow.name == "stage_plan",
                    )
                )
                == 0
            )
        restored = await PlanService(travel).stage(context, body)
        assert restored == await PlanService(travel).stage(replace(context, run_id=uuid4()), body)
        state = await travel.business_context(context)
        pending = state["pending_draft"]
        assert isinstance(pending, dict) and pending["draft_id"] == str(restored.draft_id)

    runner.run(exercise())


def test_cached_draft_does_not_reuse_expired_evidence_or_obsolete_base(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        first, _ = await destinations(travel, context)
        hotel = (await HotelService(travel).search(context, 1, limit=1))[0]
        candidate = proposal(first).model_copy(update={"hotel_evidence_id": hotel.evidence_id})
        body = StageInput.model_validate(
            {"change": {"kind": "initial", "proposal": candidate.model_dump(mode="json")}}
        )
        service = PlanService(travel)
        draft = await service.stage(context, body)
        assert await service.stage(replace(context, run_id=uuid4()), body) == draft
        async with transaction(travel.database) as db:
            row = await db.get(EvidenceRow, hotel.evidence_id)
            assert row
            evidence = EvidenceRecord.model_validate(row.payload)
            row.payload = evidence.model_copy(
                update={
                    "retrieved_at": datetime.now(UTC) - timedelta(minutes=6),
                    "valid_until": datetime.now(UTC) - timedelta(seconds=1),
                }
            ).model_dump(mode="json")
        with pytest.raises(ServiceError, match="证据已失效"):
            await service.stage(context, body)
        assert (await travel.business_context(context))["pending_draft"] is None
        valid_body = StageInput.model_validate(
            {"change": {"kind": "initial", "proposal": proposal(first).model_dump(mode="json")}}
        )
        valid = await service.stage(context, valid_body)
        # 另一份未确认草稿基于同一base；确认第一份以后不能注入为当前断点。
        alternative = proposal(first).model_copy(
            update={
                "items": (
                    proposal(first)
                    .items[0]
                    .model_copy(
                        update={"end": proposal(first).items[0].end + timedelta(minutes=10)}
                    ),
                )
            }
        )
        await service.stage(
            context,
            StageInput.model_validate(
                {"change": {"kind": "initial", "proposal": alternative.model_dump(mode="json")}}
            ),
        )
        await service.confirm(context.user_id, valid.draft_id)
        assert (await travel.business_context(context))["pending_draft"] is None

    runner.run(exercise())


@pytest.mark.parametrize("order_committed", [False, True])
def test_confirm_process_kill_on_both_sides_of_supplier_commit_queries_before_retry(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    order_committed: bool,
) -> None:
    runner, travel, context = travel_setup

    async def prepare() -> object:
        offer = HotelOffer.model_validate(
            (await HotelService(travel).search(context, 1, limit=1))[0].value
        )
        return await BookingService(travel, SupplierService(travel.database)).hold(
            context, HoldHotelInput(offer_id=offer.offer_id, expected_revision=1)
        )

    from backend.domain.booking import Booking

    held = runner.run(prepare())
    assert isinstance(held, Booking)
    commit_then_kill(
        travel,
        context,
        "confirm_after_order" if order_committed else "confirm_before_order",
        {"booking_id": str(held.booking_id)},
    )

    async def exercise() -> None:
        restored = BookingService(travel, SupplierService(travel.database))
        assert (await restored.get(context.user_id, held.booking_id)).status == "confirmed"
        expected = "booked" if order_committed else "unknown"
        result = await restored.confirm(context.user_id, held.booking_id)
        assert result.status == expected
        assert await restored.confirm(context.user_id, held.booking_id) == result
        async with transaction(travel.database) as db:
            assert await db.scalar(
                select(func.count())
                .select_from(SupplierOrderRow)
                .where(SupplierOrderRow.client_ref == held.client_ref)
            ) == int(order_committed)
            if not order_committed:
                hold_row = await db.get(SupplierHoldRow, held.client_ref)
                assert hold_row
                hold_row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        if not order_committed:
            assert (await restored.reconcile(context.user_id, held.booking_id)).status == "failed"
            async with transaction(travel.database) as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(SupplierOrderRow)
                        .where(SupplierOrderRow.client_ref == held.client_ref)
                    )
                    == 0
                )

    runner.run(exercise())


@pytest.mark.parametrize("cancelling", [False, True])
def test_api_startup_closes_interrupted_run_atomically_without_runtime_call(
    postgres_url: URL,
    cancelling: bool,
) -> None:
    sessions = SessionService(postgres_url, demo_enabled=True)
    options = {"loop_factory": asyncio.SelectorEventLoop}
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:

        async def prepare() -> tuple[RunContext, str]:
            from backend.services.sessions import DemoLogin

            identity = await sessions.create_demo_user(DemoLogin(display_name="恢复实验"))
            sid = await sessions.new_session(identity.user_id)
            async with transaction(sessions.database) as db:
                row = await runs.create(
                    db, identity.user_id, sid.session_id, uuid4(), "中断实验", "offline"
                )
                context = RunContext(identity.user_id, sid.session_id, row.id)
                await runs.append_event(db, RuntimeEvent(context, "started"))
                if cancelling:
                    row.status = "cancelling"
            return context, identity.token

        context, token = runner.run(prepare())
        runner.run(sessions.close())
    runtime = FakeRuntime(RuntimeOutcome(text="new", sdk_session_id="fake"))
    restored = SessionService(postgres_url)
    service = RunService(restored.database, runtime_factory=lambda executor: runtime)
    with TestClient(create_app(restored, runs_service=service), backend_options=options) as client:
        headers = {"Authorization": f"Bearer {token}"}
        result = client.get(f"/runs/{context.run_id}", headers=headers).json()
        expected = "cancelled" if cancelling else "partial"
        assert result["status"] == expected and result["last_sequence"] == 2
        response = client.get(f"/runs/{context.run_id}/events", headers=headers)
        assert f'"kind":"{expected}"' in response.text
        assert runtime.resumed == []
        assert client.portal
        again = client.portal.call(
            service.submit,
            context.user_id,
            context.session_id,
            MessageInput(client_message_id=uuid4(), text="继续读取最新状态"),
        )
        assert again.run_id != context.run_id

"""R17：五种单根因注入使用实际工具/PG事实；不冒充真实模型坏例。"""

import asyncio
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from backend.adapters.supplier import SupplierClient
from backend.adapters.tracing import write_trace
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeIdentity
from backend.domain.travel_request import TravelConditions
from backend.persistence.database import Database
from backend.persistence.models import EvidenceRow
from backend.services.bookings import BookingService
from backend.services.hotels import HotelService
from backend.services.travel import TravelService
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from eval.diagnostics import (
    ArgumentFact,
    Cause,
    CommitFact,
    ConditionFact,
    EvidenceFact,
    Fact,
    SupplierAttempt,
    SupplierFact,
    diagnose,
)
from mock_supplier.app import create_app
from tests.integration.http_helper import serve_http
from tests.integration.test_bookings import select_offer
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "cause",
    [
        "request_understanding",
        "tool_selection_or_args",
        "supplier_failure",
        "stale_evidence",
        "state_commit",
    ],
)
def test_single_injected_root_is_located_from_actual_tool_and_database_facts(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
    cause: Cause,
) -> None:
    runner, travel, context = travel_setup
    events: list[RuntimeEvent] = [RuntimeEvent(context, "started")]
    attempts: list[SupplierAttempt] = []

    class RecordingTransport(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            start = datetime.now(UTC)
            response = await super().handle_async_request(request)
            attempts.append(SupplierAttempt(start, datetime.now(UTC), response.status_code))
            return response

    async def execute(url: str) -> Fact:
        executor = TravelToolExecutor(travel)
        name = "update_travel_request"
        arguments: dict[str, object] = {
            "expected_revision": 1,
            "set": {"adults": 3},
            "explicit_fields": ["adults"],
        }
        previous = await travel.get_request(context)
        record = None
        if cause == "tool_selection_or_args":
            name, arguments = (
                "search_places",
                {"city": "京都", "private-secret-key": "private-secret-value"},
            )
        elif cause in {"supplier_failure", "stale_evidence"}:
            body = await select_offer(travel, context)
            name, arguments = "hold_hotel", body.model_dump(mode="json")
            record = (await HotelService(travel).known_quotes(context, (body.offer_id,)))[0]
            if cause == "stale_evidence":
                record = record.model_copy(
                    update={
                        "retrieved_at": datetime.now(UTC) - timedelta(hours=1),
                        "valid_until": datetime.now(UTC) - timedelta(minutes=1),
                    }
                )
                async with travel.database.sessions.begin() as db:
                    stored = await db.get(EvidenceRow, record.evidence_id)
                    assert stored is not None
                    stored.payload = record.model_dump(mode="json")
            else:
                executor.bookings = BookingService(
                    travel,
                    SupplierClient(
                        url,
                        headers={"X-Mock-Fault": "server_error"},
                        transport=RecordingTransport(),
                    ),
                )
        elif cause == "state_commit":
            arguments = {
                "expected_revision": previous.revision - 1,
                "set": {"adults": 3},
                "explicit_fields": ["adults"],
            }
        result = await execute_observed(
            executor,
            context,
            name,
            arguments,
            events.append,
            definition=next(d for d in DEFINITIONS if d.name == name),
        )
        start, end = events[-2:]
        assert start.tool_call_id is not None
        if cause == "request_understanding":
            actual = await travel.get_request(context)
            assert actual.adults == 3 and actual.revision == 2 and result.code is None
            return ConditionFact(
                context, start.tool_call_id, TravelConditions(adults=2), actual, actual.revision
            )
        if cause == "tool_selection_or_args":
            assert result.code == "validation"
            return ArgumentFact(context, start.tool_call_id, arguments)
        if cause == "supplier_failure":
            assert result.code == "provider_error" and len(attempts) == 1
            return SupplierFact(context, start.tool_call_id, tuple(attempts))
        if cause == "stale_evidence":
            assert record is not None and result.code == "conflict"
            return EvidenceFact(
                context, start.tool_call_id, record, start.occurred_at, previous.revision, arguments
            )
        current = await travel.get_request(context)
        assert result.code == "conflict" and current == previous
        return CommitFact(
            context, start.tool_call_id, previous.revision - 1, current.revision, True
        )

    if cause == "supplier_failure":
        with serve_http(
            create_app(Database(travel.database.engine.url), faults_enabled=True)
        ) as url:
            fact = runner.run(execute(url))
    else:
        fact = runner.run(execute("unused"))
    events.append(RuntimeEvent(context, "completed" if events[-1].code is None else "failed"))
    trace_id = write_trace(
        tmp_path / "trace.jsonl", events, RuntimeIdentity("fake", "injection", "none", "none")
    )
    result = diagnose(tuple(events), (fact,), business_passed=False, trace_id=trace_id)
    assert result.cause == cause and result.event_index == 1 and result.trace_id == trace_id
    if isinstance(fact, EvidenceFact):
        assert (
            diagnose(
                tuple(
                    replace(e, tool_name="update_travel_request") if e.tool_name else e
                    for e in events
                ),
                (fact,),
                business_passed=False,
            ).cause
            == "unknown"
        )
        for arguments in (
            {**fact.arguments, "offer_id": str(context.run_id)},
            {**fact.arguments, "expected_revision": fact.request_revision - 1},
        ):
            assert (
                diagnose(
                    tuple(events), (replace(fact, arguments=arguments),), business_passed=False
                ).cause
                == "unknown"
            )
    public = json.dumps(asdict(result))
    assert (
        "private-secret" not in public
        and "京都" not in public
        and "arguments" not in public.replace("submitted_arguments", "")
    )
    assert diagnose(tuple(events), (), business_passed=False, trace_id=trace_id).cause == "unknown"


def test_normal_actual_tool_and_database_control_has_no_failure_cause(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    events: list[RuntimeEvent] = [RuntimeEvent(context, "started")]

    async def exercise() -> None:
        result = await execute_observed(
            TravelToolExecutor(travel),
            context,
            "update_travel_request",
            {"expected_revision": 1, "set": {"adults": 3}, "explicit_fields": ["adults"]},
            events.append,
            definition=next(d for d in DEFINITIONS if d.name == "update_travel_request"),
        )
        assert result.code is None and (await travel.get_request(context)).adults == 3

    runner.run(exercise())
    events.append(RuntimeEvent(context, "completed"))
    assert diagnose(tuple(events), (), business_passed=True).cause is None

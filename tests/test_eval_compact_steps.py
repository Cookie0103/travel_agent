"""紧凑事件步骤：只保留闭合参数/已知键，不含文本、自由值和私有名称。"""

from uuid import uuid4

from backend.domain.execution import RunContext, RuntimeEvent
from eval.diagnostics import compact_steps


def test_compact_steps_drops_events_without_text_arguments_or_private_names() -> None:
    context = RunContext(uuid4())
    steps = compact_steps(
        (
            RuntimeEvent(context, "text", text="private-text"),
            RuntimeEvent(context, "tool_started", tool_name="search_hotel_offers"),
        )
    )
    assert "private-text" not in str(steps) and len(steps) == 1


def test_compact_steps_keeps_only_closed_parameters_and_known_keys() -> None:
    from backend.domain.tool_facts import argument_facts
    from backend.tools.travel import SCHEMAS

    arguments: dict[str, object] = {
        "ops": [
            {
                "key": "dietary",
                "scope": "trip",
                "op": "ADD",
                "value": "private-value",
                "quote": "private-quote",
            }
        ],
        "private-key": "private-body",
    }
    facts = argument_facts("propose_memory", arguments)
    context = RunContext(uuid4())
    event = RuntimeEvent(
        context,
        "tool_started",
        tool_name="propose_memory",
        arguments=facts,
        argument_keys=("ops", "private-key"),
    )
    steps = compact_steps((event,))
    assert steps[0]["argument_keys"] == ["ops"]
    assert "dietary" in str(steps) and "trip" in str(steps) and "ADD" in str(steps)
    assert "private" not in str(steps)
    assert argument_facts("search_hotel_offers", {"segment_arrive": "2026-11-03"}).segment_arrive
    assert (
        argument_facts("search_hotel_offers", {"segment_arrive": "private-date"}).segment_arrive
        is None
    )
    assert argument_facts("present_travel_result", {"kind": "private-kind"}).kind is None
    assert "propose_memory" in SCHEMAS


def test_choice_ids_and_malformed_free_values_do_not_enter_metadata() -> None:
    from backend.domain.tool_facts import argument_facts

    context = RunContext(uuid4())
    event = RuntimeEvent(
        context,
        "presentation",
        presentation={
            "data": {
                "component": "choice",
                "question": "private-question",
                "options": [
                    {"option_id": "keep", "label": "private-label"},
                    {"option_id": "private-id"},
                ],
            }
        },
    )
    steps = compact_steps((event,))
    assert steps[0]["choice_options"] == ["keep"]
    assert "private" not in str(steps)
    facts = argument_facts(
        "propose_memory",
        {
            "ops": [
                {
                    "key": "private-key",
                    "scope": "private-scope",
                    "op": "private-op",
                    "value": "private-value",
                }
            ]
        },
    )
    assert "private" not in facts.model_dump_json()


def test_observed_argument_facts_survive_json_roundtrip_without_free_text() -> None:
    import asyncio

    from pydantic import TypeAdapter

    from backend.domain.execution import event_metadata
    from backend.tools.contracts import ToolResult
    from backend.tools.execution import execute_observed
    from backend.tools.travel import DEFINITIONS
    from tests.test_external_tool_recovery import SyntheticExecutor

    async def exercise() -> None:
        executor = SyntheticExecutor()
        executor.responses = [ToolResult({})]
        events: list[RuntimeEvent] = []
        definition = next(d for d in DEFINITIONS if d.name == "propose_memory")
        await execute_observed(
            executor,
            RunContext(uuid4()),
            "propose_memory",
            {
                "ops": [
                    {
                        "key": "avoid",
                        "op": "ADD",
                        "scope": "trip",
                        "value": "private-value",
                        "quote": "private-quote",
                    }
                ],
            },
            events.append,
            definition=definition,
        )
        adapter = TypeAdapter(tuple[RuntimeEvent, ...])
        encoded = adapter.dump_json(tuple(event_metadata(e) for e in events))
        decoded = adapter.validate_json(encoded)
        assert "private" not in encoded.decode()
        assert decoded[0].arguments and decoded[0].arguments.ops[0].key == "avoid"
        assert "trip" in str(compact_steps(decoded))

    asyncio.run(exercise())

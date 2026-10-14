"""模型分诊只能输出闭合标签与已存在步骤，不算准确率或确定根因。"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.domain.execution import RunContext, RuntimeEvent
from eval.triage import Triage, compact_steps, validate_triage


def test_triage_compacts_events_without_text_arguments_or_private_names() -> None:
    context = RunContext(uuid4())
    steps = compact_steps(
        (
            RuntimeEvent(context, "text", text="private-text"),
            RuntimeEvent(context, "tool_started", tool_name="search_hotel_offers"),
        )
    )
    assert "private-text" not in str(steps) and len(steps) == 1
    assert validate_triage('{"first_step":0,"label":"wrong_tool"}', steps).first_step == 0
    with pytest.raises(ValueError):
        validate_triage('{"first_step":2,"label":"wrong_tool"}', steps)
    with pytest.raises(ValidationError):
        Triage.model_validate({"first_step": 0, "label": "private-freeform-label"})


def test_triage_keeps_only_closed_parameters_and_known_keys() -> None:
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


def test_required_tool_cannot_support_wrong_tool_label() -> None:
    from eval.triage import consistency_check

    steps = [{"index": 0, "kind": "tool_started", "tool": "propose_memory"}]
    wrong = Triage(label="wrong_tool", first_step=0)
    assert consistency_check(wrong, steps, required_tools=("propose_memory",)) == "不一致"
    assert consistency_check(wrong, steps, required_tools=()) == "无法判断"
    forbidden = [{"index": 0, "kind": "tool_started", "tool": "search_places"}]
    assert consistency_check(wrong, forbidden, forbidden_tools=("search_places",)) == "与事件一致"
    assert consistency_check(Triage(label="unknown"), steps) == "无法判断"
    for label in ("grader_artifact", "simulator_artifact"):
        assert Triage(label=label, first_step=0).label == label


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


@pytest.mark.parametrize(
    "case_id",
    [
        "v2-mem-trip-solo",
        "v2-mem-trip-dietary",
        "v2-mem-negation-early",
        "v2-mem-negation-walk",
        "v2-mem-update-invalidate",
    ],
)
def test_original_five_required_memory_tools_contradict_wrong_tool(case_id: str) -> None:
    from pathlib import Path

    from eval.suites import load_suite
    from eval.triage import consistency_check

    cases, _ = load_suite(Path(__file__).resolve().parents[1], "v2-memory", "dev")
    case = next(c for c in cases if c.case_id == case_id)
    assert "propose_memory" in case.required_tools
    assert (
        consistency_check(
            Triage(label="wrong_tool", first_step=0),
            [{"index": 0, "kind": "tool_started", "tool": "propose_memory"}],
            required_tools=tuple(case.required_tools),
        )
        == "不一致"
    )


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

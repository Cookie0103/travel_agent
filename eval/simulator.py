"""E7多轮合成用户：SDK无工具扮演用户，业务动作复用应用服务；每trial独立trace。"""

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import UUID, uuid4

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from sqlalchemy import select

from backend.adapters.evaluation_faults import EvaluationFault, validate_fault
from backend.adapters.tracing import cloud_exporter, push_scores
from backend.agent.runtime import EventSink
from backend.domain.choices import Answers, ChoiceSelection
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeOutcome
from backend.domain.itinerary import HotelStay
from backend.domain.travel_request import RequestPatch, pace_of
from backend.limits import ProbeError
from backend.persistence import runs as run_rows
from backend.persistence.database import configuration, database_url
from backend.persistence.models import ChoiceCardRow, PlanDraftRow
from backend.persistence.temporary import temporary_database
from backend.providers.claude_agent.application import GuardedRuntime
from backend.providers.claude_agent.live import runtime_budget
from backend.providers.claude_agent.settings import load_runtime_settings
from backend.providers.claude_agent.structured import structured_call
from backend.services.choices import ChoiceService, card_from_row
from backend.services.common import ServiceError, transaction
from backend.services.memory import MemoryService
from backend.services.plans import PlanService
from backend.services.runs import MessageInput, RunService
from backend.services.sessions import DemoLogin
from eval.database import DatabaseEvaluation, database_evaluation, selector_runner
from eval.guard import refuse_live_under_pytest
from eval.metrics import process_metrics
from eval.report import simulation_summary
from eval.run import manifest
from eval.simulator_failures import ControllerReason, failure_details
from eval.simulator_metrics import (
    claims_pass,
    dialogue_claims,
    no_reoffer_after_decline,
    saved_items_cover_segments,
)
from eval.simulator_metrics import (
    recalled as recalled,
)
from eval.state import snapshot
from scripts.dev import configure_environment

ROOT = Path(__file__).resolve().parents[1]


class UserAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["message", "choice", "hotels", "new_session", "confirm_plan", "done"]
    text: str = Field(min_length=1, max_length=4000)
    choice_id: UUID | None = None
    option_id: str | None = None
    answers: Answers | None = None
    hotel_stays: tuple[HotelStay, ...] | None = Field(default=None, min_length=1, max_length=6)
    draft_id: UUID | None = None

    @model_validator(mode="after")
    def separate_actions(self) -> "UserAction":
        expected = {
            "choice": {"choice_id", "option_id"},
            "hotels": {"hotel_stays"},
            "confirm_plan": {"draft_id"},
        }.get(self.kind, set())
        actual = {
            name
            for name in ("choice_id", "option_id", "hotel_stays", "draft_id")
            if getattr(self, name) is not None
        }
        if actual != expected:
            raise ValueError("动作字段不匹配")
        if self.answers is not None and self.kind != "choice":
            raise ValueError("表单答案只用于选择动作")
        return self


@dataclass(frozen=True)
class Scenario:
    case_id: str
    goal: str
    initial: str
    fault: EvaluationFault = "coverage"


SCENARIOS = (
    Scenario(
        "v2-user-budget-accept",
        "预算太低时接受第一档有酒店的放宽，看到可选酒店即可结束，不保存或预订",
        "请比较三家京都酒店，不保存或预订。",
        "budget-double",
    ),
    Scenario(
        "v2-user-budget-reject",
        "预算太低时点保持原预算，不能接受放宽；助手说明替代选择即可结束，不保存预订",
        "请比较京都酒店，不保存或预订。",
        "budget-double",
    ),
    Scenario(
        "v2-user-clarify",
        "被追问时提供2026-11-03到11-04、2成人、无儿童、1间房、独立房间禁烟床型不限，看到酒店即可结束",
        "我想比较京都酒店，不保存或预订。",
    ),
    Scenario(
        "v2-user-pace",
        "先比较酒店，之后要求选择旅行节奏卡，点击比较轻松，再让助手确认新节奏。不保存或预订",
        "先比较京都酒店，不保存或预订。",
    ),
    Scenario(
        "v2-user-memory-cross",
        "确认记住特种兵偏好，然后新会话只问你知道我的旅行节奏吗，不再次介绍自己；得到特种兵回答后结束",
        "我长期喜欢特种兵旅行，请给记忆确认卡，不规划。",
    ),
    Scenario(
        "v2-user-memory-trip",
        "对单人出行记忆卡点击这次而已，然后新会话问知道我平时几个人出行吗；应回答未知，不能重复偏好",
        "这次我一个人旅行，请给这次而已的确认卡，不规划。",
    ),
    Scenario(
        "v2-user-three-segments",
        "京都11-03→11-04、大阪11-04→11-05、奈良11-05→11-06，每段酒店都要选，通过hotels动作提交完整三段，再请求行程，看到草稿后confirm_plan保存。表外兴趣不知道。",
        "请给京都、大阪、奈良三个住宿段分别比较酒店，等我选择再规划，不预订。",
    ),
    Scenario(
        "v2-user-429",
        "比较酒店，中途429由助手自行恢复，看到候选即可结束，不保存或预订",
        "请比较京都酒店，不保存或预订。",
        "429-ok",
    ),
)


class TrialRuntime(GuardedRuntime):
    """只旁观SDK事件；编排、取消与计费完整复用GuardedRuntime。"""

    def __init__(
        self,
        business: DatabaseEvaluation,
        scenario: Scenario,
        repeat: int,
        observed: list[RuntimeEvent],
    ) -> None:
        super().__init__(
            ROOT,
            business.dsn(),
            evaluation_fault=scenario.fault,
            evaluation={"suite": "v2-user", "case_id": scenario.case_id, "trial": repeat},
        )
        self.observed = observed

    async def execute(
        self,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        outcome = await super().execute(context, prompt, sdk_session_id, emit, cancelled)
        self.observed.extend(self.observed_events)
        return outcome


class TrialRuns(RunService):
    """仅专用随机评测库：各应用run共享trial的trace根，不改生产消息协议。"""

    def __init__(
        self,
        business: DatabaseEvaluation,
        scenario: Scenario,
        trial: int,
        trace_id: str,
        directory: Path,
        cloud: bool,
        observed: list[RuntimeEvent],
    ) -> None:
        validate_fault(scenario.fault, profile="eval", database_dsn=business.dsn())
        super().__init__(
            business.sessions.database,
            live_enabled=True,
            trace_cloud=cloud,
            trace_directory=directory,
            runtime_factory=lambda _: TrialRuntime(business, scenario, trial, observed),
        )


async def page(business: DatabaseEvaluation, context: RunContext) -> dict[str, object]:
    async with transaction(business.sessions.database) as db:
        ids = list(
            await db.scalars(
                select(ChoiceCardRow.id).where(
                    ChoiceCardRow.session_id == context.session_id,
                    ChoiceCardRow.answered_run_id.is_(None),
                )
            )
        )
        drafts = list(
            await db.scalars(
                select(PlanDraftRow.id).where(
                    PlanDraftRow.session_id == context.session_id,
                    PlanDraftRow.confirmed_version.is_(None),
                )
            )
        )
    cards = [
        await ChoiceService(business.travel).get(context.user_id, context.session_id, card_id)
        for card_id in ids
    ]
    return {
        "choices": [c.model_dump(mode="json") for c in cards if not c.stale],
        "draft_ids": [str(d) for d in drafts],
    }


def pace_chosen(row: ChoiceCardRow) -> bool:
    if row.kind == "pace":
        return row.answered_option_id == "relaxed"
    form = card_from_row(row, row.expected_revision).form
    return form is not None and any(
        group.key == "pace" and group.selected == ("relaxed",) for group in form.groups
    )


async def trial(
    business: DatabaseEvaluation,
    scenario: Scenario,
    repeat: int,
    directory: Path,
    cloud: bool,
    trace_id: str,
) -> dict[str, object]:
    identity = await business.sessions.create_demo_user(DemoLogin(display_name="多轮合成用户"))
    session = await business.sessions.new_session(identity.user_id)
    context = RunContext(identity.user_id, session.session_id)
    first_session = session.session_id
    conditions: dict[str, object] = {"city": "京都"}
    if scenario.case_id != "v2-user-clarify":
        conditions.update(
            start_date="2026-11-03",
            end_date="2026-11-04",
            adults=2,
            child_ages=[],
            rooms=1,
            currency="JPY",
            transport="walk",
            lodging_budget={
                "amount": {"upper": "10000"},
                "basis": "per_room_night",
                "currency": "JPY",
            },
            hard_constraints=["住宿：独立房间", "房型：禁烟", "床型：无要求"],
        )
    if scenario.case_id == "v2-user-three-segments":
        conditions.pop("end_date")
        conditions["segments"] = [
            {"city": city, "arrive": f"2026-11-0{index + 3}", "depart": f"2026-11-0{index + 4}"}
            for index, city in enumerate(("京都", "大阪", "奈良"))
        ]
        conditions["lodging_budget_unlimited"] = True
        conditions.pop("lodging_budget")
    await business.travel.patch_request(
        context, RequestPatch.model_validate({"expected_revision": 0, "set": conditions})
    )
    transcript: list[dict[str, object]] = []
    events: list[RuntimeEvent] = []
    service = TrialRuns(business, scenario, repeat, trace_id, directory / "traces", cloud, events)
    action = UserAction(kind="message", text=scenario.initial)
    error: str | None = None
    controller_failure: dict[str, object] | None = None
    failure_reason: ControllerReason = "service_rejected"
    raw_simulator_output: str | None = None
    rejected_action: dict[str, object] | None = None
    initial_orders = (await snapshot(business.travel, context)).orders
    try:
        for turn in range(8):
            rejected_action = action.model_dump(mode="json")
            failure_reason = "service_rejected"
            if action.kind == "done":
                break
            if action.kind == "new_session":
                context = RunContext(
                    identity.user_id,
                    (await business.sessions.new_session(identity.user_id)).session_id,
                )
            current_page = await page(business, context)
            request = await business.travel.read_request(context)
            if action.kind == "confirm_plan":
                draft_ids = current_page["draft_ids"]
                if (
                    scenario.case_id != "v2-user-three-segments"
                    or not isinstance(draft_ids, list)
                    or str(action.draft_id) not in draft_ids
                ):
                    failure_reason = "unauthorized_draft"
                    raise ValueError("未授权或不存在的确认草稿")
                assert action.draft_id
                await PlanService(business.travel).confirm(identity.user_id, action.draft_id)
                transcript.append(
                    {"user": action.model_dump(mode="json"), "answer": "服务器已确认保存合成行程"}
                )
                break
            selection = None
            if action.kind == "choice":
                assert action.choice_id and action.option_id
                failure_reason = "choice_missing"
                card = await ChoiceService(business.travel).get(
                    identity.user_id, context.session_id, action.choice_id
                )
                if (
                    card.stale
                    or card.answered_option_id
                    or action.option_id not in {o.option_id for o in card.options}
                ):
                    failure_reason = (
                        "stale_choice"
                        if card.stale
                        else "answered_choice"
                        if card.answered_option_id
                        else "unknown_option"
                    )
                    raise ValueError("模拟用户选择无效")
                selection = ChoiceSelection(
                    choice_id=action.choice_id, option_id=action.option_id, answers=action.answers
                )
            failure_reason = "invalid_simulator_output"
            message = MessageInput(
                client_message_id=uuid4(),
                text=action.text,
                mode="deepseek",
                expected_revision=request.revision if selection or action.hotel_stays else None,
                selection=selection,
                hotel_stays=action.hotel_stays,
            )
            failure_reason = "service_rejected"
            submitted = await service.submit(identity.user_id, context.session_id, message)
            task = service.tasks.get(submitted.run_id)
            if task:
                await task
            result = await service.get(identity.user_id, submitted.run_id)
            context = RunContext(identity.user_id, context.session_id, result.run_id)
            async with transaction(business.sessions.database) as db:
                recorded = await run_rows.owned(db, identity.user_id, result.run_id)
                answered_at = recorded.finished_at if recorded else None
            transcript.append(
                {
                    "user": action.model_dump(mode="json"),
                    "answer": result.answer,
                    "status": result.status,
                    "presentations": list(result.presentations),
                    "session_id": str(context.session_id),
                    "run_id": str(context.run_id),
                    "answered_at": answered_at.isoformat() if answered_at else None,
                }
            )
            visible = await page(business, context)
            failure_reason = "simulator_unavailable"
            raw_simulator_output, rejected_action = None, None
            response, _ = await asyncio.to_thread(
                structured_call,
                "simulator",
                {
                    "persona": "简短耐心的旅行用户",
                    "hidden_goal": scenario.goal,
                    "hidden_fields": conditions,
                    "dialogue": transcript[-4:],
                    "page": visible,
                    "round": turn + 1,
                    "limit": 8,
                },
                ROOT,
                trace_cloud=cloud,
                evaluation={"suite": "v2-user", "case_id": scenario.case_id, "trial": repeat},
            )
            raw_simulator_output = response
            failure_reason = "invalid_simulator_output"
            action = UserAction.model_validate_json(response)
    except (ValueError, ServiceError, ProbeError) as failure:
        error = type(failure).__name__
        controller_failure = failure_details(failure_reason, raw_simulator_output, rejected_action)
    finally:
        await service.close()
    request = await business.travel.read_request(context)
    final = await snapshot(business.travel, context)
    facts = await MemoryService(business.sessions.database).facts(identity.user_id)
    process = process_metrics(tuple(events), "\n".join(str(t["answer"]) for t in transcript))
    first_errors = process["user_visible_first_errors"]
    recovered = process["recovered_without_user"]
    assert isinstance(first_errors, int) and isinstance(recovered, int)
    checks = {
        "no_orders": initial_orders == final.orders,
        "no_first_error": first_errors == 0,
        "controller_valid": error is None,
        "finished": bool(transcript) and action.kind in {"done", "confirm_plan"},
        "completed_runs": all(t.get("status", "completed") == "completed" for t in transcript),
    }
    case_id = scenario.case_id
    no_reoffer: bool | None = None
    shown = any(
        isinstance(e.presentation, dict)
        and isinstance(data := e.presentation.get("data"), dict)
        and data.get("component") == "hotel_comparison"
        and bool(data.get("cards") or data.get("segments"))
        for e in events
    )
    if case_id.startswith("v2-user-budget"):
        checks["budget_choice"] = (
            request.lodging_budget is not None
            and request.lodging_budget.amount.upper
            == Decimal("20000" if case_id.endswith("accept") else "10000")
        )
        async with transaction(business.sessions.database) as db:
            chosen = await db.scalar(
                select(ChoiceCardRow.id).where(
                    ChoiceCardRow.session_id == context.session_id,
                    ChoiceCardRow.kind == "budget_relaxation",
                    ChoiceCardRow.answered_option_id
                    == ("accept" if case_id.endswith("accept") else "keep"),
                )
            )
        checks["budget_answered"] = chosen is not None
        checks["hotel_options"] = shown and any(
            e.tool_name == "search_hotel_offers"
            and e.kind == "tool_finished"
            and not e.code
            and e.result_empty is False
            for e in events
        )
        if case_id.endswith("reject"):
            no_reoffer = no_reoffer_after_decline(transcript)
            if no_reoffer is not None:
                checks["no_reoffer_after_decline"] = no_reoffer
    elif case_id == "v2-user-clarify":
        checks["clarified"] = (
            str(request.start_date) == "2026-11-03"
            and str(request.end_date) == "2026-11-04"
            and request.adults == 2
            and request.child_ages == ()
            and request.rooms == 1
            and all(
                value in request.hard_constraints
                for value in ("住宿：独立房间", "房型：禁烟", "床型：无要求")
            )
        )
        checks["hotel_delivery"] = shown and any(
            e.tool_name == "search_hotel_offers"
            and e.kind == "tool_finished"
            and e.result_empty is False
            and not e.code
            for e in events
        )
    elif case_id == "v2-user-pace":
        checks["hotel_delivery"] = hotel_delivered(tuple(events))
        checks["pace"] = pace_of(request) == "慢节奏"
        async with transaction(business.sessions.database) as db:
            rows = await db.scalars(
                select(ChoiceCardRow).where(
                    ChoiceCardRow.session_id == context.session_id,
                    ChoiceCardRow.kind.in_(("pace", "form")),
                    ChoiceCardRow.answered_option_id.is_not(None),
                )
            )
            clicked = any(pace_chosen(row) for row in rows)
        checks["pace_clicked"] = clicked
    elif case_id in {"v2-user-memory-cross", "v2-user-memory-trip"}:
        checks["new_session"] = context.session_id != first_session
        key = "pace" if case_id.endswith("cross") else "companion_pattern"
        checks["confirmed_scope"] = any(
            f.key == key
            and f.status == "active"
            and f.scope == ("long_term" if case_id.endswith("cross") else "trip")
            for f in facts
        )
        injected = await MemoryService(business.sessions.database).snapshot(context)
        checks["injected_scope"] = any(f["key"] == key for f in injected) == case_id.endswith(
            "cross"
        )
        answer = str(transcript[-1]["answer"]) if transcript else ""
        checks["recall"] = recalled(answer, long_term=case_id.endswith("cross"))
    elif case_id == "v2-user-three-segments":
        checks["saved_three"] = (
            final.saved is not None and len(final.saved.content.hotel_stays) == 3
        )
        checks["saved_items_cover_segments"] = saved_items_cover_segments(final.saved, conditions)
        constraints = await business.saved_constraints(context)
        checks["saved_no_conflicts"] = (
            constraints.get("delivered") is True
            and constraints.get("status") in {"complete", "partial"}
            and constraints.get("conflict_count") == 0
        )
    else:
        checks["hotel_delivery"] = hotel_delivered(tuple(events))
        checks["recovered"] = any(
            e.kind == "tool_finished"
            and e.tool_name == "search_hotel_offers"
            and e.code is None
            and e.external
            and e.external.recovered_from
            for e in events
        )
    claims = dialogue_claims(transcript, tuple(events))
    claim_result = claims_pass(claims)
    if claim_result is not None:
        checks["claim_consistency"] = claim_result
    row: dict[str, object] = {
        "case_id": case_id,
        "trial": repeat,
        "trace_id": trace_id,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "claim_consistency": claims,
        "no_reoffer_after_decline": no_reoffer,
        "error": error,
        "controller_failure": controller_failure,
        "rounds": len(transcript),
        "text": str(transcript[-1]["answer"]) if transcript else "",
        "user_input": scenario.initial,
        "conditions": conditions,
        "dialogue": transcript,
        "process": process,
        "steps": TypeAdapter(tuple[RuntimeEvent, ...]).dump_python(tuple(events), mode="json"),
        "saved_plan": final.saved.model_dump(mode="json") if final.saved else None,
        "saved_constraints": await business.saved_constraints(context),
    }
    if cloud:
        push_scores(
            trace_id,
            {
                "rule_pass": int(row["status"] == "passed"),
                "first_error_visible": first_errors,
            },
        )
    return row


def hotel_delivered(events: tuple[RuntimeEvent, ...]) -> bool:
    shown = any(
        isinstance(e.presentation, dict)
        and isinstance(data := e.presentation.get("data"), dict)
        and data.get("component") == "hotel_comparison"
        and bool(data.get("cards") or data.get("segments"))
        for e in events
    )
    return shown and any(
        e.kind == "tool_finished"
        and e.tool_name == "search_hotel_offers"
        and e.code is None
        and e.result_empty is False
        for e in events
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--trace-cloud", action="store_true")
    parser.add_argument("--repeat", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--case-id", action="append", default=[])
    args = parser.parse_args(argv)
    refuse_live_under_pytest(args.live)
    cases = [s for s in SCENARIOS if not args.case_id or s.case_id in args.case_id]
    if not args.live:
        print(json.dumps({"prepared": len(cases), "repeat": args.repeat, "http_attempts": 0}))
        return 0
    configure_environment()
    import os

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    directory = ROOT / ".cache" / "simulator" / uuid4().hex
    directory.mkdir(parents=True)
    source_manifest = {
        **manifest([]),
        "suite": "v2-user",
        "scenarios": [asdict(s) for s in cases],
        "repeat": args.repeat,
        "max_user_turns": 8,
    }
    (directory / "manifest.json").write_text(
        json.dumps(source_manifest, ensure_ascii=False, default=str, indent=2) + "\n",
        encoding="utf-8",
    )
    budget = runtime_budget(ROOT, load_runtime_settings(os.environ))
    rows = []
    with (
        temporary_database(database_url(configuration()), "eval") as url,
        selector_runner() as runner,
    ):

        async def execute() -> None:
            async with database_evaluation(url) as business:
                for scenario in cases:
                    for repeat in range(1, args.repeat + 1):
                        budget.check_authorization()
                        _, before = budget.totals()
                        trial_started = perf_counter()
                        provider = TracerProvider(
                            resource=Resource({"service.name": "travel-agent"}),
                            sampler=ALWAYS_ON,
                            shutdown_on_exit=False,
                        )
                        with (directory / f"{scenario.case_id}-{repeat}-root.jsonl").open(
                            "w", encoding="utf-8"
                        ) as handle:
                            provider.add_span_processor(
                                SimpleSpanProcessor(ConsoleSpanExporter(out=handle))
                            )
                            if args.trace_cloud:
                                exporter = cloud_exporter(os.environ)
                                if exporter:
                                    provider.add_span_processor(SimpleSpanProcessor(exporter))
                            with provider.get_tracer("travel-agent").start_as_current_span(
                                "evaluation.trial",
                                attributes={
                                    "eval_case_id": scenario.case_id,
                                    "trial": repeat,
                                    "suite": "v2-user",
                                    "langfuse.observation.type": "chain",
                                    "langfuse.trace.metadata.git_sha": str(
                                        source_manifest["code_commit"]
                                    ),
                                    "langfuse.trace.metadata.suite": "v2-user",
                                    "langfuse.trace.tags": ("deepseek", "v2-user"),
                                    "langfuse.trace.metadata.eval_case_id": scenario.case_id,
                                    "langfuse.trace.metadata.eval_trial": repeat,
                                },
                            ) as span:
                                trace_id = format(span.get_span_context().trace_id, "032x")
                                row = await trial(
                                    business,
                                    scenario,
                                    repeat,
                                    directory,
                                    args.trace_cloud,
                                    trace_id,
                                )
                                span.set_attribute("rule_pass", row["status"] == "passed")
                            provider.shutdown()
                        _, after = budget.totals()
                        row["cost_cny"] = str(after - before)
                        row["elapsed_seconds"] = round(perf_counter() - trial_started, 6)
                        rows.append(row)
                        with (directory / "results.jsonl").open("a", encoding="utf-8") as output:
                            output.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                        print(
                            scenario.case_id,
                            repeat,
                            row["status"],
                            row["checks"],
                            row["cost_cny"],
                            flush=True,
                        )
                        if len(rows) == 1:
                            print(
                                "first_trial_estimate_cny",
                                str((after - before) * len(cases) * args.repeat),
                                flush=True,
                            )

        runner.run(execute())
    (directory / "summary.json").write_text(
        json.dumps(
            simulation_summary(rows, args.repeat),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""v3评测入口：脚本化用户逐题多轮；离线夹具只证明设施，--live才调用真实模型与数据源。

uv run python -m eval.v3_run                       # 离线冒烟（FixtureRuntime，零外部调用）
uv run python -m eval.v3_run --live --case-id <id> # 真实DeepSeek/乐天/Google/Open-Meteo
"""

import argparse
import asyncio
import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from sqlalchemy import func, select

from backend.adapters.evaluation_faults import is_eval_database
from backend.adapters.tracing import cloud_exporter, push_scores
from backend.agent.fixture_runtime import FixtureRuntime
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeOutcome
from backend.domain.hotel_flow import current_picks, flow_from_details
from backend.domain.plans import PlanDraft
from backend.domain.travel_request import RequestPatch, pace_of
from backend.persistence import travel as request_rows
from backend.persistence.models import MemoryFactRow, PlanDraftRow, SupplierOrderRow
from backend.persistence.temporary import temporary_database
from backend.providers.claude_agent.application import GuardedRuntime
from backend.services.common import transaction
from backend.services.memory import MemoryService
from backend.services.runs import RunService
from backend.services.sessions import DemoLogin
from backend.services.travel import request_from_row
from eval.claims import ClaimFacts
from eval.database import DatabaseEvaluation, database_evaluation, selector_runner
from eval.guard import refuse_live_under_pytest
from eval.memory_metrics import memory_scores, proposal_failures
from eval.state import prepare_state, snapshot
from eval.v3_cases import DEFAULT_CASES, ROOT, V3Case, load_cases
from eval.v3_judge import JudgeCall, judge_scores, judge_trial, write_transcript
from eval.v3_report import write_reports
from eval.v3_score import DbFacts, Observation, Score, TurnObs, score_trial
from eval.v3_user import ScriptResult, ScriptRunner, StructuredCall

PROFILES = ("human", "default", "relaxed")
PROMPT_ENV = "TRAVEL_EVAL_PROMPT_SNAPSHOT"
SCORE_FLAGS = (
    "success",
    "hard_pass",
    "false_claim",
    "within_time",
    "tool_ok",
    "memory_ok",
    "abandoned",
)


class Recording:
    """把runtime事件旁路记录到按run分组的表里；其余编排/取消/计费沿用被包装的运行时。"""

    def __init__(self, store: dict[UUID, list[RuntimeEvent]]) -> None:
        self.store = store

    def tee(
        self, context: RunContext, emit: Callable[[RuntimeEvent], None]
    ) -> Callable[[RuntimeEvent], None]:
        def forward(event: RuntimeEvent) -> None:
            self.store.setdefault(context.run_id, []).append(event)
            emit(event)

        return forward


class OfflineRuntime(FixtureRuntime):
    def __init__(self, executor: Any, store: dict[UUID, list[RuntimeEvent]]) -> None:
        super().__init__(executor)
        self.recording = Recording(store)

    async def execute(  # type: ignore[no-untyped-def]
        self, context, prompt, sdk_session_id, emit, cancelled
    ) -> RuntimeOutcome:
        return await super().execute(
            context, prompt, sdk_session_id, self.recording.tee(context, emit), cancelled
        )


class V3Runtime(GuardedRuntime):
    """live运行时：fault为空走真实数据，否则走合成故障数据（两者互斥）；开启prompt快照。"""

    def __init__(
        self,
        business: DatabaseEvaluation,
        case: V3Case,
        repeat: int,
        store: dict[UUID, list[RuntimeEvent]],
    ) -> None:
        super().__init__(
            ROOT,
            business.dsn(),
            real_data=case.fault is None,
            evaluation_fault=case.fault,
            evaluation={
                "suite": "v3",
                "case_id": case.case_id,
                "trial": repeat,
                "category": case.category,
            },
            prompt_snapshot=True,
        )
        self.recording = Recording(store)

    async def execute(  # type: ignore[no-untyped-def]
        self, context, prompt, sdk_session_id, emit, cancelled
    ) -> RuntimeOutcome:
        outcome = await super().execute(
            context, prompt, sdk_session_id, self.recording.tee(context, emit), cancelled
        )
        return outcome


@dataclass
class TrialConfig:
    live: bool
    cloud: bool
    directory: Path
    meta: Mapping[str, str]
    budget: Any = None  # live: 提供totals()->(…, Decimal)
    structured: StructuredCall | None = None
    judge: bool = False  # live默认开；离线只有测试注入judge_call时才评审
    judge_check: bool = False
    judge_call: JudgeCall | None = None
    scores_sink: list[dict[str, float]] = field(default_factory=list)


async def create_trial_context(business: DatabaseEvaluation, case: V3Case) -> RunContext:
    identity = await business.sessions.create_demo_user(DemoLogin(display_name="v3评测用户"))
    session = await business.sessions.new_session(identity.user_id)
    context = RunContext(identity.user_id, session.session_id)
    state = case.setup
    if state is not None:
        fields = state.request.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        if fields:
            await business.travel.patch_request(
                context, RequestPatch.model_validate({"expected_revision": 0, "set": fields})
            )
        await prepare_state(
            business.travel, context, state, business.supplier_url or "http://127.0.0.1:8001"
        )
    return context


def hotel_cards(turns: Sequence[TurnObs]) -> list[dict[str, Any]]:
    return [
        c
        for t in turns
        for e in t.events
        for d in [e.presentation.get("data") if e.presentation else None]
        if isinstance(d, dict) and d.get("component") == "hotel_comparison"
        for c in d.get("cards") or []
        if isinstance(c, dict)
    ]


async def pick_count(business: DatabaseEvaluation, context: RunContext) -> int:
    async with transaction(business.sessions.database) as db:
        row = await request_rows.owned_request(db, context)
        if row is None:
            return 0
        return len(current_picks(flow_from_details(row.request_details), request_from_row(row)))


async def facts_at(
    business: DatabaseEvaluation, context: RunContext, turns: Sequence[TurnObs]
) -> ClaimFacts:
    """某轮刚结束时的服务端事实：到此为止展示过的酒店卡、当前会话的选择、当前用户已生效的记忆。"""
    cards = hotel_cards(turns)
    facts = await MemoryService(business.sessions.database).facts(context.user_id)
    return ClaimFacts(
        within_budget_cards=(not any(c.get("budget_excess") for c in cards)) if cards else None,
        hotel_selected=await pick_count(business, context) > 0,
        memory_active=any(f.status == "active" for f in facts),
    )


async def count_orders(business: DatabaseEvaluation) -> int:
    async with transaction(business.sessions.database) as db:
        return int(await db.scalar(select(func.count()).select_from(SupplierOrderRow)) or 0)


async def collect(
    business: DatabaseEvaluation,
    case: V3Case,
    result: ScriptResult,
    events: dict[UUID, list[RuntimeEvent]],
    orders_before: int,
) -> Observation:
    """脚本结束后的终态事实；不调用inspect_memory（它会删除偏好）。"""
    turns = tuple(result.turns)
    final = result.context
    assert final is not None
    first_user = result.users["A"]
    after = await snapshot(business.travel, final)
    request = await business.travel.read_request(final)
    memory = MemoryService(business.sessions.database)
    async with transaction(business.sessions.database) as db:
        drafts = list(
            await db.scalars(
                select(PlanDraftRow).where(
                    PlanDraftRow.user_id == final.user_id,
                    PlanDraftRow.session_id == final.session_id,
                )
            )
        )
    picks = await pick_count(business, final)
    latest = max(drafts, key=lambda d: str(d.payload.get("expires_at")), default=None)
    validation = (
        tuple(
            c.model_dump(mode="json")
            for c in PlanDraft.model_validate(latest.payload).validation.checks
        )
        if latest is not None
        else None
    )
    state = {
        "request": {**request.model_dump(mode="json"), "pace": pace_of(request)},
        "saved_version": after.saved.version if after.saved else 0,
        "hotel_stays": [s.model_dump(mode="json") for s in after.saved.content.hotel_stays]
        if after.saved
        else [],
        "bookings": [b.card() for b in after.bookings],
        "memory": await memory.snapshot(final),
    }
    current_facts = tuple(
        f.model_dump(mode="json") for f in await memory.facts(final.user_id, include_history=True)
    )
    owner_facts = (
        current_facts
        if first_user == final.user_id
        else tuple(
            f.model_dump(mode="json") for f in await memory.facts(first_user, include_history=True)
        )
    )
    flat = [e for t in turns for e in t.events]
    layer1: Mapping[str, object] | None = None
    if case.memory.l1:
        run_ids = {UUID(t.run_id) for t in turns}
        async with transaction(business.sessions.database) as db:
            facts = list(
                await db.scalars(
                    select(MemoryFactRow).where(MemoryFactRow.source_run_id.in_(run_ids))
                )
            )
        predictions = [
            {"key": f.key, "value": f.value, "scope": f.scope, "op": "ADD"} for f in facts
        ]
        layer1 = memory_scores(
            [e.model_dump(mode="json") for e in case.memory.l1],
            predictions,
            invalid_attempts=proposal_failures(tuple(flat))["invalid_attempts"],
        )
    return Observation(
        turns=turns,
        validation=validation,
        state=state,
        db=DbFacts(
            draft_exists=bool(drafts),
            plan_saved=after.saved is not None,
            new_orders=max(0, await count_orders(business) - orders_before),
            hotel_selected_segments=picks,
            memory_current=current_facts,
            memory_owner=owner_facts,
        ),
        memory_l1=layer1,
        claim_facts=ClaimFacts(
            within_budget_cards=(not any(c.get("budget_excess") for c in cards))
            if (cards := hotel_cards(turns))
            else None,
            hotel_selected=picks > 0,
            memory_active=any(f.get("status") == "active" for f in current_facts),
        ),
        step_unavailable=result.step_unavailable,
        infra_error=result.infra_error,
    )


def prompt_reader_for(
    business: DatabaseEvaluation, config: TrialConfig
) -> Callable[[RunContext], Any]:
    async def read(context: RunContext) -> str | None:
        if config.live:
            path = (
                ROOT
                / ".cache"
                / "sessions"
                / str(context.user_id)
                / str(context.session_id)
                / f"system-prompt-{context.run_id}.txt"
            )
            return path.read_text(encoding="utf-8") if path.exists() else None
        snap = await MemoryService(business.sessions.database).snapshot(context)
        return json.dumps(snap, ensure_ascii=False)

    return read


async def run_trial(
    business: DatabaseEvaluation,
    case: V3Case,
    repeat: int,
    config: TrialConfig,
    trace_id: str | None,
) -> dict[str, object]:
    events: dict[UUID, list[RuntimeEvent]] = {}
    if config.live:
        service = RunService(
            business.sessions.database,
            live_enabled=True,
            trace_cloud=config.cloud,
            trace_directory=config.directory / "traces",
            runtime_factory=lambda _: V3Runtime(business, case, repeat, events),
        )
    else:
        service = RunService(
            business.sessions.database,
            trace_directory=config.directory / "traces",
            runtime_factory=lambda executor: OfflineRuntime(executor, events),
        )
    started = perf_counter()
    result = ScriptResult()
    orders_before = 0
    try:
        context = await create_trial_context(business, case)
        orders_before = await count_orders(business)
        runner = ScriptRunner(
            case,
            business,
            service,
            events,
            mode="live" if config.live else "offline",
            root=ROOT,
            prompt_reader=prompt_reader_for(business, config),
            facts_reader=lambda ctx, turns: facts_at(business, ctx, turns),
            structured=config.structured if config.live else None,
        )
        await runner.start(context.user_id, context.session_id)
        result = await runner.run()
    except Exception as error:  # 设施故障：该trial记infra_error，不拖垮整批
        result.infra_error = f"harness:{type(error).__name__}"
        if result.context is None:
            result.context = RunContext(uuid4(), uuid4())
    finally:
        await service.close()
    try:
        observation = await collect(business, case, result, events, orders_before)
    except Exception as error:
        observation = Observation(
            turns=tuple(result.turns),
            infra_error=result.infra_error or f"collect:{type(error).__name__}",
        )
    observation = replace(
        observation, l3_source="prompt_snapshot" if config.live else "service_snapshot"
    )
    score = score_trial(case, observation)
    transcript = write_transcript(config.directory, case, repeat, observation)
    judge = None
    if config.judge and config.judge_call is not None and observation.turns:
        # 评审与被测运行同处trial前后账本窗口内，成本计入cost_cny；任何失败只记judge_error。
        judge = await asyncio.to_thread(
            judge_trial, case, observation, config.judge_call, ROOT, check=config.judge_check
        )
    return trial_row(
        case,
        repeat,
        trace_id,
        score,
        observation,
        perf_counter() - started,
        judge=judge,
        transcript=transcript,
    )


def trial_row(
    case: V3Case,
    repeat: int,
    trace_id: str | None,
    score: Score,
    observation: Observation,
    elapsed: float,
    *,
    judge: dict[str, object] | None = None,
    transcript: str | None = None,
) -> dict[str, object]:
    turns: list[TurnObs] = list(observation.turns)
    return {
        "case_id": case.case_id,
        "category": case.category,
        "trial": repeat,
        "repeat": repeat,
        "status": "passed" if score.success else "failed",
        "success": score.success,
        "reason": score.reason,
        "trace_id": trace_id,
        "flags": {name: getattr(score, name) for name in SCORE_FLAGS},
        "soft_score": score.soft_score,
        "metrics": score.metrics,
        "total_s": round(elapsed, 3),
        "max_turn_s": score.metrics.get("turn_latency_max_s", 0.0),
        "ttfua_s": score.metrics.get("ttfua_s", 0.0),
        "turn_ttfua_s": [round(t.ttfua_s, 3) for t in turns],
        "claim_violations": list(score.claim_violations),
        "claim_unknown": score.claim_unknown,
        "checks": [
            {"id": c.id, "tier": c.tier, "outcome": c.outcome, "detail": c.detail}
            for c in score.checks
        ],
        "memory_layers": score.memory_layers,
        "l3_source": score.l3_source,
        "tools": score.tool_summary,
        "judge_yes_rate": judge.get("yes_rate") if judge else None,
        "judge": judge,
        "transcript_path": transcript,
        "infra_error": score.infra_error,
        "step_unavailable": observation.step_unavailable,
        "turns": [
            {
                "index": t.index,
                "user": t.user,
                "status": t.status,
                "error_code": t.error_code,
                "latency_s": round(t.latency_s, 3),
                "ttfua_s": round(t.ttfua_s, 3),
                "abandoned": t.abandoned,
                "answer": t.answer[:2000],
            }
            for t in turns
        ],
    }


def configure_profile(profile: str) -> None:
    if profile == "default":
        os.environ.pop("TRAVEL_PROFILE", None)
    else:
        os.environ["TRAVEL_PROFILE"] = profile


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


async def run_all(
    business: DatabaseEvaluation,
    cases: list[V3Case],
    repeat: int,
    config: TrialConfig,
    *,
    max_cny: float | None,
    on_row: Callable[[dict[str, object]], None],
) -> str | None:
    """顺序执行所有trial；返回提前停止的原因（超出费用上限）或None。"""
    spent = Decimal(0)
    for case in cases:
        for trial in range(1, repeat + 1):
            if max_cny is not None and spent >= Decimal(str(max_cny)):
                return f"max_cny_reached:{spent}"
            if config.budget is not None:
                config.budget.check_authorization()  # 每个trial前复核授权（同v2模拟器）
            before = config.budget.totals()[1] if config.budget is not None else Decimal(0)
            provider = TracerProvider(
                resource=Resource({"service.name": "travel-agent"}),
                sampler=ALWAYS_ON,
                shutdown_on_exit=False,
            )
            root_file = config.directory / f"{case.case_id}-{trial}-root.jsonl"
            with root_file.open("w", encoding="utf-8") if config.live else nullcontext() as handle:
                if handle is not None:
                    provider.add_span_processor(
                        SimpleSpanProcessor(ConsoleSpanExporter(out=handle))
                    )
                if config.cloud:
                    exporter = cloud_exporter(os.environ)
                    if exporter:
                        provider.add_span_processor(SimpleSpanProcessor(exporter))
                attributes: dict[str, Any] = {
                    "eval_case_id": case.case_id,
                    "trial": trial,
                    "suite": "v3",
                    "langfuse.observation.type": "chain",
                    "langfuse.trace.tags": (
                        "v3",
                        case.category,
                        "deepseek",
                        config.meta["profile"],
                    ),
                    "langfuse.trace.metadata.suite": "v3",
                    "langfuse.trace.metadata.eval_case_id": case.case_id,
                    "langfuse.trace.metadata.eval_trial": trial,
                    "langfuse.trace.metadata.category": case.category,
                    "langfuse.trace.metadata.git_sha": config.meta["git_sha"],
                    "langfuse.trace.metadata.run_name": config.meta["run_name"],
                    "langfuse.trace.metadata.trial_group": config.meta["trial_group"],
                    "langfuse.trace.metadata.fault": case.fault or "none",
                }
                with provider.get_tracer("travel-agent").start_as_current_span(
                    "evaluation.trial", attributes=attributes
                ) as span:
                    trace_id = format(span.get_span_context().trace_id, "032x")
                    row = await run_trial(business, case, trial, config, trace_id)
                    span.set_attribute("rule_pass", bool(row["success"]))
                provider.shutdown()
            after = config.budget.totals()[1] if config.budget is not None else Decimal(0)
            cost = after - before
            spent += cost
            row["cost_cny"] = str(cost)
            finish_trial(row, config)
            on_row(row)
    return None


def finish_trial(row: dict[str, object], config: TrialConfig) -> None:
    """所有分数在trial结束时一次性批量推送，且只推数值。"""
    flags = row["flags"]
    metrics = row["metrics"]
    assert isinstance(flags, dict) and isinstance(metrics, dict)
    # within_time为None=题目没设时限：不适用就不推（延迟数值始终推送）。
    payload: dict[str, float] = {k: float(v) for k, v in flags.items() if v is not None}
    if row["soft_score"] is not None:
        payload["soft_score"] = float(row["soft_score"])  # type: ignore[arg-type]
    payload.update({k: float(v) for k, v in metrics.items()})
    tools = row["tools"]
    assert isinstance(tools, dict)
    payload["required_tools_ok"] = float(not tools["missing_required"])
    payload["forbidden_tools_ok"] = float(not tools["forbidden_used"])
    payload["hallucinated_tool"] = float(bool(tools["hallucinated"]))
    payload["blocked_run"] = float(bool(tools["blocked"]))
    layers = row["memory_layers"]
    assert isinstance(layers, dict)
    names = {
        "l1": "mem_l1_exact",
        "l2": "mem_l2_persisted",
        "l3": "mem_l3_in_prompt",
        "l4": "mem_l4_behavior",
    }
    payload.update({names[k]: float(v) for k, v in layers.items()})
    payload.update(judge_scores(row.get("judge")))  # type: ignore[arg-type]
    payload["cost_cny"] = float(str(row.get("cost_cny", "0")))
    config.scores_sink.append(payload)
    trace_id = row.get("trace_id")
    if config.cloud and isinstance(trace_id, str):
        push_scores(trace_id, payload, batch=True)


def require_snapshot_database(cases: Sequence[V3Case], live: bool, dsn: str) -> None:
    """live且有题声明L3时，评测库必须过is_eval_database，否则prompt快照不会落盘。"""
    if (
        live
        and not is_eval_database(dsn)
        and any(c.memory.l3.present or c.memory.l3.absent for c in cases)
    ):
        raise ValueError(
            "声明了memory.l3的题需要专用评测库(travel_agent_eval_<hex>)才能写prompt快照；已中止"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--trace-cloud", action="store_true")
    parser.add_argument("--repeat", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--profile", choices=PROFILES, default="human")
    parser.add_argument(
        "--max-cny",
        type=float,
        default=None,
        help="可选的软上限（默认不限）：只在两个trial之间检查累计花费，最多可超出一个trial。",
    )
    parser.add_argument(
        "--no-judge", action="store_true", help="--live默认开启rubric评审；加此项关闭"
    )
    parser.add_argument(
        "--judge-check",
        action="store_true",
        help="用另一套措辞重评通用项，报告翻转率（评审成本约翻倍）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    refuse_live_under_pytest(args.live)
    if args.trace_cloud and not args.live:
        parser.error("--trace-cloud需要--live")
    if args.max_cny is not None and args.max_cny <= 0:
        parser.error("--max-cny必须为正数")
    if args.judge_check and (args.no_judge or not args.live):
        parser.error("--judge-check需要--live且不能与--no-judge同用")
    cases = [c for c in load_cases(args.cases) if not args.case_id or c.case_id in args.case_id]
    if args.case_id and len(cases) != len(set(args.case_id)):
        parser.error("有case-id不在题库里")
    from scripts.dev import configure_environment

    configure_environment()
    configure_profile(args.profile)
    run_name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    directory = ROOT / ".cache" / "eval-v3" / run_name
    directory.mkdir(parents=True)
    budget = None
    structured: StructuredCall | None = None
    if args.live:
        from dotenv import load_dotenv

        from backend.providers.claude_agent.live import runtime_budget
        from backend.providers.claude_agent.settings import load_runtime_settings
        from backend.providers.claude_agent.structured import structured_call

        load_dotenv(ROOT / ".env", override=False)
        if any(c.memory.l3.present or c.memory.l3.absent for c in cases):
            os.environ[PROMPT_ENV] = "1"
        budget = runtime_budget(ROOT, load_runtime_settings(os.environ))
        budget.check_authorization()
        structured = structured_call
    meta = {
        "git_sha": git_sha(),
        "run_name": run_name,
        "trial_group": run_name,
        "profile": args.profile if args.live else "offline",
    }
    config = TrialConfig(
        args.live,
        args.trace_cloud,
        directory,
        meta,
        budget,
        structured,
        judge=args.live and not args.no_judge,
        judge_check=args.judge_check,
        judge_call=structured if args.live else None,
    )
    manifest = {
        "run_name": run_name,
        "live": args.live,
        "profile": args.profile,
        "repeat": args.repeat,
        "cases": [c.case_id for c in cases],
        "cases_file": str(args.cases),
        "max_cny": args.max_cny,
        "judge": config.judge,
        "judge_check": config.judge_check,
        "git_sha": meta["git_sha"],
        "started_at": datetime.now(UTC).isoformat(),
        "prompt_snapshot_env": os.environ.get(PROMPT_ENV) == "1",
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    rows: list[dict[str, object]] = []
    stopped: list[str | None] = [None]

    def record(row: dict[str, object]) -> None:
        rows.append(row)
        with (directory / "trials.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        print(
            row["case_id"],
            row["trial"],
            row["status"],
            row["reason"],
            row.get("cost_cny"),
            flush=True,
        )

    with (
        temporary_database(_database_url(), "eval") as url,
        selector_runner() as runner,
    ):

        async def execute() -> None:
            async with database_evaluation(url) as business:
                stopped[0] = await run_all(
                    business, cases, args.repeat, config, max_cny=args.max_cny, on_row=record
                )

        try:
            require_snapshot_database(cases, args.live, url.render_as_string(hide_password=False))
        except ValueError as error:
            print(error)
            return 2
        runner.run(execute())
    write_reports(directory, manifest, rows, args.repeat, stopped[0])
    print(directory)
    return 0


def _database_url() -> Any:
    from backend.persistence.database import configuration, database_url

    return database_url(configuration())


if __name__ == "__main__":
    raise SystemExit(main())

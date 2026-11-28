"""v3离线冒烟：FixtureRuntime只证明设施——脚本步骤、卡片点击、新会话、换用户、放弃、兜底与评分推送。"""

import asyncio
import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import URL

from backend.agent.fixture_runtime import FixtureRuntime
from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeOutcome
from backend.limits import ProbeError
from backend.persistence.temporary import temporary_database
from backend.services.choices import ChoiceService
from backend.services.runs import RunService
from backend.tools.execution import execute_observed
from backend.tools.skill_config import SkillConfig
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from eval.core.database import DatabaseEvaluation, database_evaluation
from eval.simulator.run import page
from eval.v3.cases import V3Case
from eval.v3.run import (
    OfflineRuntime,
    TrialConfig,
    collect,
    count_orders,
    create_trial_context,
    facts_at,
    run_all,
)
from eval.v3.score import score_trial
from eval.v3.user import ScriptResult, ScriptRunner
from tests.support.runner import selector_runner

pytestmark = pytest.mark.integration

REQUEST = {
    "city": "京都",
    "start_date": "2026-11-03",
    "end_date": "2026-11-04",
    "adults": 2,
    "child_ages": [],
    "rooms": 1,
    "currency": "JPY",
    "transport": "walk",
    "lodging_budget": {
        "amount": {"upper": "10000"},
        "basis": "per_room_night",
        "currency": "JPY",
    },
    "hard_constraints": ["住宿：独立房间", "房型：禁烟", "床型：无要求"],
}
BASE: dict[str, Any] = {
    "case_id": "smoke",
    "category": "main_flow",
    "title": "冒烟",
    "setup": {"request": REQUEST},
    "rubric": [{"id": f"r{i}", "q": "q"} for i in range(3)],
}
type Played = tuple[ScriptResult, dict[UUID, list[RuntimeEvent]], int]


def make(**changes: Any) -> V3Case:
    return V3Case.model_validate({**BASE, **changes})


class ScriptedRuntime(OfflineRuntime):
    """在夹具之外按提示词发一张节奏卡/提问/卡死，仅用于驱动脚本层。"""

    async def execute(  # type: ignore[no-untyped-def]
        self, context, prompt, sdk_session_id, emit: EventSink, cancelled: asyncio.Event
    ) -> RuntimeOutcome:
        tee = self.recording.tee(context, emit)
        if prompt.startswith("出卡"):
            assert isinstance(self.executor, TravelToolExecutor)
            travel = self.executor.travel
            request = await travel.read_request(context)
            await ChoiceService(travel).create(context, "pace", request.revision)
            tee(RuntimeEvent(context, "text", text="请选节奏"))
            return RuntimeOutcome("请选节奏", "sdk")
        if prompt == "追问本次交通":
            text = "这次旅行想用哪种交通方式？"
            tee(RuntimeEvent(context, "text", text=text))
            return RuntimeOutcome(text, "sdk")
        if prompt == "这次步行，继续生成行程。":
            assert isinstance(self.executor, TravelToolExecutor)
            request = await self.executor.travel.read_request(context)
            definition = next(d for d in DEFINITIONS if d.name == "update_travel_request")
            result = await execute_observed(
                self.executor,
                context,
                "update_travel_request",
                {"expected_revision": request.revision, "set": {"transport": "walk"}},
                tee,
                definition=definition,
            )
            assert result.code is None
            return await super().execute(context, "演示：生成行程", sdk_session_id, emit, cancelled)
        if prompt.startswith("追问"):
            tee(RuntimeEvent(context, "text", text="你们几个人出行？"))
            return RuntimeOutcome("你们几个人出行？", "sdk")
        if prompt.startswith("限流"):
            return RuntimeOutcome(code="rate_limited", reason="provider_rate_limit")
        if prompt.startswith("慢速"):
            await asyncio.sleep(0.4)
            tee(RuntimeEvent(context, "text", text="慢但完成"))
            return RuntimeOutcome("慢但完成", "sdk")
        if prompt.startswith("卡死"):
            await cancelled.wait()
            return RuntimeOutcome(code="cancelled", reason="cancelled")
        return await super().execute(context, prompt, sdk_session_id, emit, cancelled)


async def play(business: DatabaseEvaluation, case: V3Case, structured: Any = None) -> Played:
    events: dict[UUID, list[RuntimeEvent]] = {}
    service = RunService(
        business.sessions.database,
        trace_directory=Path("/tmp/v3-smoke-traces"),
        runtime_factory=lambda executor: ScriptedRuntime(executor, events),
    )
    context = await create_trial_context(business, case)
    orders = await count_orders(business)

    async def reader(ctx: RunContext) -> str | None:
        return "读取的提示词"

    runner = ScriptRunner(
        case,
        business,
        service,
        events,
        mode="offline",
        root=Path("."),
        prompt_reader=reader,
        structured=structured,
        facts_reader=lambda ctx, turns: facts_at(business, ctx, turns),
    )
    await runner.start(context.user_id, context.session_id)
    try:
        result = await runner.run()
    finally:
        await service.close()
    return result, events, orders


def in_eval_db(postgres_url: URL, body: Any) -> None:
    with temporary_database(postgres_url, "eval") as url, selector_runner() as runner:

        async def go() -> None:
            async with database_evaluation(url) as business:
                await body(business)

        runner.run(go())


def test_messages_card_click_new_session_and_switch_user(postgres_url: URL) -> None:
    case = make(
        user_script=[
            {"say": "演示：比较酒店"},
            {"say": "出卡"},
            {"card": {"kind": "pace", "option": "relaxed"}},
            {"new_session": True},
            {"say": "演示：比较酒店"},
            {"switch_user": "B"},
            {"say": "你好"},
        ],
        memory={"l3": {"present": ["读取"], "absent": ["不存在的词"]}},
    )

    async def body(business: DatabaseEvaluation) -> None:
        result, events, orders = await play(business, case)
        assert result.step_unavailable is None and result.infra_error is None
        assert [t.user for t in result.turns] == ["A", "A", "A", "A", "B"]
        assert [t.fresh_session for t in result.turns] == [False, False, False, True, True]
        assert len({t.session_id for t in result.turns}) == 3  # 初始、new_session、B
        assert any(c.kind == "pace" for c in result.turns[1].cards)
        assert any(e.kind == "tool_started" for e in result.turns[0].events)
        assert all(t.claim_facts is not None for t in result.turns)  # 逐轮事实
        assert result.turns[0].claim_facts.hotel_selected is False  # type: ignore[union-attr]
        assert set(result.users) == {"A", "B"} and result.users["A"] != result.users["B"]
        observation = await collect(business, case, result, events, orders)
        score = score_trial(case, observation)
        assert score.memory_layers == {"l3": True}
        assert observation.db.new_orders == 0 and not observation.db.plan_saved
        # 点击后第一个会话里不再有未答的节奏卡，且点击确实产生了一轮run
        assert (await page(business, result.sessions[0]))["choices"] == []
        assert result.turns[2].session_id == result.turns[1].session_id

    in_eval_db(postgres_url, body)


def test_missing_card_is_step_unavailable_unless_skippable(postgres_url: URL) -> None:
    async def body(business: DatabaseEvaluation) -> None:
        hard = make(
            user_script=[
                {"say": "你好"},
                {"card": {"kind": "memory_confirm", "option": "remember"}},
            ]
        )
        result, events, orders = await play(business, hard)
        assert result.step_unavailable == 2 and len(result.turns) == 1
        score = score_trial(hard, await collect(business, hard, result, events, orders))
        assert not score.success and score.reason == "step_unavailable:2"
        soft = make(
            user_script=[
                {"card": {"kind": "memory_confirm", "if_missing": "skip"}},
                {"say": "你好"},
            ]
        )
        skipped, *_ = await play(business, soft)
        assert skipped.step_unavailable is None and len(skipped.turns) == 1

    in_eval_db(postgres_url, body)


def test_conditional_transport_reply_unblocks_an_offline_draft(
    postgres_url: URL, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make(
        setup={"request": {**REQUEST, "transport": None}},
        user_script=[
            {"say": "追问本次交通"},
            {
                "say": "这次步行，继续生成行程。",
                "when": ["transport_unset", "no_draft"],
            },
            {"say": "不应再补充交通。", "when": ["transport_unset"]},
            {"say": "不应再要求草稿。", "when": ["no_draft"]},
        ],
        hard_checks=[{"id": "draft", "type": "db", "assert": "draft_no_conflict"}],
    )

    monkeypatch.setattr(
        "eval.v3.run.OfflineRuntime", lambda executor, events, _: ScriptedRuntime(executor, events)
    )
    trials = tmp_path / "trials.jsonl"

    def write_row(row: dict[str, object]) -> None:
        with trials.open("a", encoding="utf-8") as output:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")

    async def body(business: DatabaseEvaluation) -> None:
        config = TrialConfig(
            False,
            False,
            tmp_path,
            {"profile": "offline", "git_sha": "smoke", "run_name": "smoke", "trial_group": "smoke"},
        )
        assert await run_all(business, [case], 1, config, max_cny=None, on_row=write_row) is None

    in_eval_db(postgres_url, body)
    [line] = trials.read_text(encoding="utf-8").splitlines()
    row = json.loads(line)
    assert row["step_unavailable"] is None and row["infra_error"] is None
    assert row["success"] and len(row["turns"]) == 2
    assert "哪种交通方式" in row["turns"][0]["answer"]
    assert row["conditional_reply_count"] == 1
    assert row["conditional_reply_predicates"] == [["transport_unset", "no_draft"]]


def test_confirm_plan_without_draft_is_step_unavailable(postgres_url: URL) -> None:
    async def body(business: DatabaseEvaluation) -> None:
        result, *_ = await play(business, make(user_script=[{"confirm_plan": True}]))
        assert result.step_unavailable == 1 and result.turns == []

    in_eval_db(postgres_url, body)


def test_slow_run_is_cancelled_and_marked_abandoned(postgres_url: URL) -> None:
    async def body(business: DatabaseEvaluation) -> None:
        case = make(user_script=[{"say": "卡死"}, {"say": "不应执行"}]).model_copy(
            update={"patience_s": 0.3}
        )
        result, events, orders = await play(business, case)
        assert len(result.turns) == 1 and result.turns[0].abandoned
        score = score_trial(case, await collect(business, case, result, events, orders))
        assert score.abandoned and score.reason == "abandoned"

    in_eval_db(postgres_url, body)


def test_fallback_policies(postgres_url: URL) -> None:
    calls: list[object] = []

    def structured(kind: str, payload: object, root: Path) -> tuple[str, dict[str, object]]:
        calls.append(payload)
        return '{"kind": "message", "text": "两个人"}', {}

    def forbidden(kind: str, payload: object, root: Path) -> tuple[str, dict[str, object]]:
        raise AssertionError("不应调用LLM")

    async def body(business: DatabaseEvaluation) -> None:
        script = [{"say": "追问"}]
        idk = make(user_script=script, fallback={"policy": "idk", "max_extra_turns": 1})
        result, *_ = await play(business, idk, forbidden)
        assert len(result.turns) == 2  # 第2轮是固定的“不知道”，没有LLM
        facts = make(
            user_script=script,
            fallback={"policy": "facts", "max_extra_turns": 2},
            user_facts={"人数": "2"},
        )
        result, *_ = await play(business, facts, structured)
        assert len(result.turns) == 3 and len(calls) == 2  # 每次追问都回答，直到上限
        result, *_ = await play(business, facts, None)  # 离线不得调用LLM：等同stop
        assert len(result.turns) == 1
        result, *_ = await play(business, make(user_script=script), forbidden)
        assert len(result.turns) == 1  # policy=stop

    in_eval_db(postgres_url, body)


class StepBudget:
    """每个trial前后各读一次：每个trial恰花1CNY，所以第一个trial结束后触发--max-cny=1。"""

    def __init__(self) -> None:
        self.reads = 0
        self.authorizations = 0

    def check_authorization(self) -> None:
        self.authorizations += 1

    def totals(self) -> tuple[int, Decimal]:
        self.reads += 1
        return 0, Decimal(self.reads // 2)


def test_run_all_pushes_numeric_scores_only_and_stops_at_cost_cap(
    postgres_url: URL, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pushed: list[tuple[str, dict[str, Any], bool]] = []

    def capture(trace_id: str, scores: Mapping[str, float], *, batch: bool = False) -> bool:
        pushed.append((trace_id, dict(scores), batch))
        return True

    monkeypatch.setattr("eval.v3.run.push_scores", capture)
    monkeypatch.setattr("eval.v3.run.cloud_exporter", lambda environment: None)
    case = make(
        user_script=[{"say": "演示：比较酒店"}, {"hotel_pick": {"rank": "first"}}],
        hard_checks=[{"id": "nothing-saved", "type": "db", "assert": "no_plan_saved"}],
    )
    other = make(case_id="smoke-two", user_script=[{"say": "你好"}])
    rows: list[dict[str, object]] = []
    budget = StepBudget()

    async def body(business: DatabaseEvaluation) -> None:
        meta = {"git_sha": "x", "run_name": "t", "trial_group": "t", "profile": "offline"}
        config = TrialConfig(False, True, tmp_path, meta, budget)
        stopped = await run_all(business, [case, other], 2, config, max_cny=1.0, on_row=rows.append)
        assert stopped is not None and stopped.startswith("max_cny_reached")

    in_eval_db(postgres_url, body)
    assert budget.authorizations == 1  # 每个实际启动的trial前都复核授权
    assert len(rows) == 1 and rows[0]["case_id"] == "smoke" and rows[0]["cost_cny"] == "1"
    presentations = rows[0]["hotel_presentations"]
    picks = rows[0]["selected_hotels"]
    assert isinstance(presentations, list) and isinstance(picks, list) and len(picks) == 1
    assert picks[0]["quote_hash"] == presentations[0]["cards"][0]["quote_hash"]
    assert len(pushed) == 1
    trace_id, payload, batch = pushed[0]
    assert len(trace_id) == 32 and batch is True
    assert payload and all(type(v) is float for v in payload.values())
    expected = {"success", "hard_pass", "ttfua_s", "turn_latency_max_s", "cost_cny"}
    assert expected <= set(payload)
    assert "within_time" not in payload  # 没设时限：不适用就不推
    assert "soft_score" not in payload and not any(k.startswith("mem_") for k in payload)


def test_authorization_failure_stops_before_any_trial(postgres_url: URL, tmp_path: Path) -> None:
    class Revoked(StepBudget):
        def check_authorization(self) -> None:
            raise ProbeError("blocked", "授权为0")

    rows: list[dict[str, object]] = []

    async def body(business: DatabaseEvaluation) -> None:
        meta = {"git_sha": "x", "run_name": "t", "trial_group": "t", "profile": "offline"}
        config = TrialConfig(False, False, tmp_path, meta, Revoked())
        with pytest.raises(ProbeError):
            await run_all(
                business,
                [make(user_script=[{"say": "你好"}])],
                1,
                config,
                max_cny=5.0,
                on_row=rows.append,
            )

    in_eval_db(postgres_url, body)
    assert rows == []


def test_no_patience_means_no_cancellation_and_latency_is_only_recorded(postgres_url: URL) -> None:
    async def body(business: DatabaseEvaluation) -> None:
        case = make(user_script=[{"say": "慢速"}])
        assert case.patience_s is None and case.ttfua_s is None
        result, events, orders = await play(business, case)
        assert not result.turns[0].abandoned and result.turns[0].answer == "慢但完成"
        assert result.turns[0].latency_s >= 0.4
        score = score_trial(case, await collect(business, case, result, events, orders))
        assert (
            score.success
            and score.within_time is None
            and score.metrics["turn_latency_max_s"] >= 0.4
        )

    in_eval_db(postgres_url, body)


def judged_rows(
    postgres_url: URL,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    judge_call: Any,
    case: V3Case | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, Any]]]:
    pushed: list[dict[str, Any]] = []

    def capture(trace_id: str, scores: Mapping[str, float], *, batch: bool = False) -> bool:
        pushed.append(dict(scores))
        return True

    monkeypatch.setattr("eval.v3.run.push_scores", capture)
    monkeypatch.setattr("eval.v3.run.cloud_exporter", lambda environment: None)
    rows: list[dict[str, object]] = []
    target = case or make(user_script=[{"say": "演示：比较酒店"}])

    async def body(business: DatabaseEvaluation) -> None:
        meta = {"git_sha": "x", "run_name": "t", "trial_group": "t", "profile": "offline"}
        config = TrialConfig(False, True, tmp_path, meta, None, judge=True, judge_call=judge_call)
        await run_all(business, [target], 1, config, max_cny=None, on_row=rows.append)

    in_eval_db(postgres_url, body)
    return rows, pushed


def test_judge_results_are_recorded_pushed_as_numbers_and_cost_stays_in_trial(
    postgres_url: URL, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[Any] = []

    def judge(kind: str, payload: Any, root: Path) -> tuple[str, dict[str, object]]:
        calls.append((kind, payload))
        ids = [i["id"] for i in payload["items"]]
        verdicts = {i: "yes" for i in ids} | {"g-no-reask": "unknown", "r1": "no"}
        results = [{"id": i, "verdict": v, "reason": "ok"} for i, v in verdicts.items()]
        return json.dumps({"results": results}), {}

    rows, pushed = judged_rows(postgres_url, monkeypatch, tmp_path, judge)
    assert len(calls) == 1 and calls[0][0] == "rubric"  # 每个trial一次
    assert "演示：比较酒店" in json.dumps(calls[0][1], ensure_ascii=False)
    row = rows[0]
    judge_result: Any = row["judge"]
    assert judge_result["error"] is None and judge_result["unknown_n"] == 1
    assert row["judge_yes_rate"] == pytest.approx(5 / 6)
    assert (tmp_path / str(row["transcript_path"])).exists()
    payload = pushed[0]
    assert payload["judge_yes_rate"] == pytest.approx(5 / 6) and payload["judge_unknown_n"] == 1.0
    assert payload["judge_r1"] == 0.0 and payload["judge_g-tone"] == 1.0
    assert "judge_g-no-reask" not in payload
    assert all(type(v) is float for v in payload.values())


def test_judge_error_never_changes_success(
    postgres_url: URL, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def broken(kind: str, payload: object, root: Path) -> tuple[str, dict[str, object]]:
        raise RuntimeError("judge down")

    rows, pushed = judged_rows(postgres_url, monkeypatch, tmp_path, broken)
    assert rows[0]["status"] == "passed" and rows[0]["success"] is True
    judge_result: Any = rows[0]["judge"]
    assert judge_result["error"] == "judge_error:RuntimeError" and rows[0]["judge_yes_rate"] is None
    assert not any(k.startswith("judge_") for k in pushed[0])


def test_provider_rate_limit_is_an_infra_error_that_stops_the_script(postgres_url: URL) -> None:
    async def body(business: DatabaseEvaluation) -> None:
        case = make(user_script=[{"say": "限流"}, {"say": "不应执行"}])
        result, events, orders = await play(business, case)
        assert result.infra_error == "rate_limited" and len(result.turns) == 1
        score = score_trial(case, await collect(business, case, result, events, orders))
        assert score.reason == "infra_error" and score.infra_error == "rate_limited"

    in_eval_db(postgres_url, body)


def test_v3_skill_variants_run_two_offline_turns(
    postgres_url: URL, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    candidate_text = "用于离线验证的酒店比较候选内容。"
    (candidate / "hotel-comparison.md").write_text(candidate_text, encoding="utf-8")
    new_text = "触发：离线演示。\n\n本次用于核对候选说明确实可被读取。"
    (candidate / "evolution-candidate.md").write_text(new_text, encoding="utf-8")
    case = make(user_script=[{"say": "第一轮"}, {"say": "第二轮"}])
    seen: list[tuple[str | None, str | None, object]] = []
    extra: list[tuple[str | None, object]] = []

    async def load_skills(
        runtime: FixtureRuntime,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        definition = next(item for item in DEFINITIONS if item.name == "load_skill")
        comparison = await execute_observed(
            runtime.executor,
            context,
            "load_skill",
            {"name": "hotel-comparison"},
            emit,
            definition=definition,
        )
        revision = await execute_observed(
            runtime.executor,
            context,
            "load_skill",
            {"name": "itinerary-revision"},
            emit,
            definition=definition,
        )
        seen.append((comparison.code, revision.code, comparison.data.get("instructions")))
        novel = await execute_observed(
            runtime.executor,
            context,
            "load_skill",
            {"name": "evolution-candidate"},
            emit,
            definition=definition,
        )
        extra.append((novel.code, novel.data.get("instructions")))
        return RuntimeOutcome("离线验收完成", "fixture-skill-session")

    monkeypatch.setattr(FixtureRuntime, "execute", load_skills)

    async def body(business: DatabaseEvaluation) -> None:
        for index, skills in enumerate(
            (
                SkillConfig(variant="no_skills"),
                SkillConfig(disabled="hotel-comparison"),
                SkillConfig(directory=candidate),
            )
        ):
            output = tmp_path / str(index)
            output.mkdir()
            config = TrialConfig(
                False,
                False,
                output,
                {
                    "profile": "offline",
                    "git_sha": "smoke",
                    "run_name": "smoke",
                    "trial_group": "smoke",
                },
                skills=skills,
            )
            rows: list[dict[str, object]] = []
            assert (
                await run_all(business, [case], 1, config, max_cny=None, on_row=rows.append) is None
            )
            assert len(rows) == 1 and rows[0]["infra_error"] is None

    in_eval_db(postgres_url, body)
    assert seen == [
        ("validation", "validation", None),
        ("validation", "validation", None),
        ("validation", None, None),
        ("validation", None, None),
        (None, None, candidate_text),
        (None, None, candidate_text),
    ]
    assert extra == [("validation", None)] * 4 + [(None, new_text)] * 2

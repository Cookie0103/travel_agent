"""原始输出先按schema/来源过滤，另计非法尝试；明确区分无分母与满分。"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from uuid import uuid4

from sqlalchemy import JSON, select

from backend.agent.fixture_runtime import FixtureRuntime
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeOutcome
from backend.domain.memory import MemoryProposal
from backend.domain.preferences import PreferencePatch, PreferenceVersion
from backend.persistence import runs
from backend.persistence.models import ChoiceCardRow, MemoryFactRow
from backend.services.common import ServiceError, transaction
from backend.services.memory import MemoryService
from backend.services.preferences import PreferenceService
from backend.services.runs import MessageInput, RunService
from backend.services.sessions import DemoLogin
from backend.tools.search import SearchExecutor
from eval.cases import Case
from eval.database import DatabaseEvaluation

FREE_KEYS = frozenset({"avoid", "dietary", "interest"})
SCORER_VERSION = "memory-v3-normalized-polarity"
MODIFIERS = (
    "这次旅行",
    "本次旅行",
    "不喜欢",
    "避免",
    "不要",
    "不想",
    "尽量",
    "这次",
    "本次",
    "只在",
    "长期",
    "一直",
)
NEGATIVE = re.compile(r"不(?:太|想|愿意|要)?(?:喜欢|吃|爱)|不要|不想|讨厌|拒绝")


def normalized_surface(value: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKC", value)
        if not c.isspace() and not unicodedata.category(c).startswith("P")
    )


def normalized_value(value: str) -> str:
    text = normalized_surface(value)
    while True:
        prefix = next((word for word in MODIFIERS if text.startswith(word)), None)
        if prefix is None:
            return text
        text = text[len(prefix) :]


def free_value_matches(key: str, value: str, expected: str) -> bool:
    # 先检查原始方向，再去掉修饰；avoid的key本身表达避免，不要求值重复否定。
    raw = normalized_surface(value)
    if key == "avoid" and re.search(r"(?:不想|不要|不愿意|不)(?:再|去)?(?:避免|讨厌|排斥)", raw):
        return False
    if key == "avoid" and any(
        not re.search(r"(?:不|没)(?:太|很|怎么)?$", raw[: m.start()])
        for m in re.finditer("喜欢", raw)
    ):
        return False
    if key in {"dietary", "interest"} and bool(NEGATIVE.search(raw)) != bool(
        NEGATIVE.search(normalized_surface(expected))
    ):
        return False
    core = normalized_value(expected)
    return bool(core) and core in normalized_value(value)


def matches(expected: Mapping[str, object], prediction: Mapping[str, object]) -> bool:
    values = expected.get("values")
    if not all(
        expected.get(k) == prediction.get(k) for k in ("key", "scope", "op")
    ) or not isinstance(values, (tuple, list)):
        return False
    key, value = expected.get("key"), prediction.get("value")
    if key not in FREE_KEYS or not isinstance(key, str) or not isinstance(value, str):
        return value in values
    return any(isinstance(gold, str) and free_value_matches(key, value, gold) for gold in values)


def memory_scores(
    expected: Sequence[Mapping[str, object]],
    predictions: Sequence[Mapping[str, object]],
    *,
    invalid_attempts: int,
) -> dict[str, object]:
    remaining = list(expected)
    true_positive = 0
    for prediction in predictions:
        matched = next((item for item in remaining if matches(item, prediction)), None)
        if matched is not None:
            remaining.remove(matched)
            true_positive += 1
    false_positive = len(predictions) - true_positive
    false_negative = len(remaining)
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": true_positive / len(predictions) if predictions else None,
        "recall": true_positive / len(expected) if expected else None,
        "invalid_attempts": invalid_attempts,
        "exact": false_positive == false_negative == invalid_attempts == 0,
        "basis": "source/schema-valid proposals; invalid attempts separate; uncalibrated",
        "scorer_version": SCORER_VERSION,
    }


async def confirmation_isolated(
    business: DatabaseEvaluation, owner: RunContext, foreign: RunContext
) -> bool:
    """真实提交入口：外用户确认本轮拥有者卡须404，事实与卡状态都不变。"""
    memory = MemoryService(business.sessions.database)
    session = await business.sessions.new_session(owner.user_id)
    original = "这是记忆确认隔离测试原话"
    async with transaction(business.sessions.database) as db:
        run = await runs.create(db, owner.user_id, session.session_id, uuid4(), original, "offline")
        context = RunContext(owner.user_id, session.session_id, run.id)
    cards = await memory.propose(
        context,
        MemoryProposal.model_validate(
            {"ops": [{"op": "ADD", "key": "interest", "value": "隔离确认样本", "quote": original}]}
        ),
    )
    async with transaction(business.sessions.database) as db:
        await runs.finish(db, context, RuntimeOutcome(text="等待合成确认检查"))
    before = await memory.facts(owner.user_id, include_history=True)
    service = RunService(
        business.sessions.database, runtime_factory=lambda _: FixtureRuntime(SearchExecutor())
    )
    blocked = False
    try:
        await service.submit(
            foreign.user_id,
            foreign.session_id,
            MessageInput.model_validate(
                {
                    "client_message_id": uuid4(),
                    "text": "记住",
                    "expected_revision": 0,
                    "selection": {"choice_id": cards[0]["choice_id"], "option_id": "remember"},
                }
            ),
        )
    except ServiceError as error:
        blocked = error.status == 404
    finally:
        await service.close()
    async with transaction(business.sessions.database) as db:
        card = await db.get(ChoiceCardRow, cards[0]["choice_id"])
        unchanged = card is not None and card.answered_option_id is None
    return (
        blocked and unchanged and await memory.facts(owner.user_id, include_history=True) == before
    )


async def inspect_memory(
    business: DatabaseEvaluation, context: RunContext, case: Case, events: tuple[RuntimeEvent, ...]
) -> dict[str, object]:
    memory = MemoryService(business.sessions.database)
    async with transaction(business.sessions.database) as db:
        facts = list(
            await db.scalars(
                select(MemoryFactRow).where(
                    MemoryFactRow.user_id == context.user_id,
                    MemoryFactRow.source_run_id == context.run_id,
                )
            )
        )
        cards = list(
            await db.scalars(
                select(ChoiceCardRow).where(
                    ChoiceCardRow.session_id == context.session_id,
                    ChoiceCardRow.source_run_id == context.run_id,
                    ChoiceCardRow.kind == "memory_confirm",
                )
            )
        )
        operations = {str(row.content["fact_id"]): row.content["operation"] for row in cards}
        predictions = [
            {"key": f.key, "value": f.value, "scope": f.scope, "op": operations.get(str(f.id))}
            for f in facts
        ]
    failures = proposal_failures(events)
    measured = memory_scores(
        [item.model_dump(mode="json") for item in case.expected_memory],
        predictions,
        invalid_attempts=failures["invalid_attempts"],
    )
    measured.update(category=case.memory_category, predictions=predictions, **failures)
    # 独立服务器不变量：拥有者检查先于事实状态；全忘记清正文与回顾，而原用户历史保留。
    owned = tuple(f for f in await memory.facts(context.user_id) if f.status == "active")
    if not owned:
        current = await PreferenceService(business.sessions.database).get(context.user_id)
        await PreferenceService(business.sessions.database).change(
            context.user_id,
            PreferencePatch.model_validate(
                {"expected_revision": current.revision, "set": {"interests": ["隔离金丝雀"]}}
            ),
        )
        owned = tuple(f for f in await memory.facts(context.user_id) if f.status == "active")
    identity = await business.sessions.create_demo_user(DemoLogin(display_name="记忆隔离合成用户"))
    session = await business.sessions.new_session(identity.user_id)
    isolation = True
    probes = 0
    confirmation: bool | None = None
    if owned:
        fact = owned[0]
        for action in (
            lambda: memory.get(identity.user_id, fact.fact_id),
            lambda: memory.delete(
                identity.user_id, fact.fact_id, PreferenceVersion(expected_revision=0)
            ),
        ):
            probes += 1
            try:
                await action()
                isolation = False
            except ServiceError as error:
                isolation &= error.status == 404
        async with transaction(business.sessions.database) as db:
            row = await runs.create(
                db, identity.user_id, session.session_id, uuid4(), case.input, "offline"
            )
            foreign = RunContext(identity.user_id, session.session_id, row.id)
        try:
            probes += 1
            await memory.propose(
                foreign,
                MemoryProposal.model_validate(
                    {
                        "ops": [
                            {
                                "op": "INVALIDATE",
                                "key": fact.key,
                                "quote": case.input[:200],
                                "target_fact_id": str(fact.fact_id),
                            }
                        ]
                    }
                ),
            )
            isolation = False
        except ServiceError as error:
            isolation &= error.status == 404
        finally:
            async with transaction(business.sessions.database) as db:
                await runs.finish(db, foreign, RuntimeOutcome(text="隔离合成检查结束"))
        confirmation = await confirmation_isolated(business, context, foreign)
    preference = await PreferenceService(business.sessions.database).get(context.user_id)
    await PreferenceService(business.sessions.database).change(
        context.user_id, PreferenceVersion(expected_revision=preference.revision)
    )
    async with transaction(business.sessions.database) as db:
        residue = await db.scalar(
            select(MemoryFactRow.id)
            .where(
                MemoryFactRow.user_id == context.user_id,
                ((MemoryFactRow.value.is_not(None)) & (MemoryFactRow.value != JSON.NULL))
                | (MemoryFactRow.evidence_quote != ""),
            )
            .limit(1)
        )
    snapshot = await business.travel.business_context(context)
    measured.update(
        cross_user_leakage=not (isolation and confirmation)
        if probes == 3 and confirmation is not None
        else None,
        isolation_probes=probes,
        cross_user_confirmation_blocked=confirmation,
        confirmation_isolation_probes=int(confirmation is not None),
        isolation_probe_total=probes + int(confirmation is not None),
        deletion_residue=residue is not None
        or bool(snapshot["memory"])
        or bool(snapshot["recent_dialogue"]),
        invariant_scope="facts, active snapshot, old dialogue cutoff; original history kept",
    )
    return measured


def proposal_failures(events: tuple[RuntimeEvent, ...]) -> dict[str, int]:
    failed = [
        e
        for e in events
        if e.kind == "tool_finished" and e.tool_name == "propose_memory" and e.code is not None
    ]
    invalid = sum(
        e.code in {"validation", "conflict", "blocked"}
        and e.reason not in {"tool_call_cap", "deadline_exceeded", "budget_exceeded"}
        for e in failed
    )
    return {"invalid_attempts": invalid, "unavailable_attempts": len(failed) - invalid}

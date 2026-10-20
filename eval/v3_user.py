"""v3脚本化用户：逐步对RunService执行；只有显式facts兜底时才会调用LLM。"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select

from backend.domain.choices import ChoiceSelection
from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.itinerary import HotelStay
from backend.persistence import plans, runs
from backend.persistence.models import ChoiceCardRow
from backend.services.common import ServiceError, transaction
from backend.services.plans import PlanService
from backend.services.runs import MessageInput, RunService
from backend.services.sessions import DemoLogin
from eval.claims import ClaimFacts
from eval.database import DatabaseEvaluation
from eval.simulator import UserAction, page
from eval.v3_cases import CardStep, HotelPickStep, Step, V3Case
from eval.v3_score import CardObs, TurnObs

IDK_TEXT = "不知道，你决定吧。"
DEFAULT_PICK_TEXT = "我选这家酒店。"
DEFAULT_CARD_TEXT = "好的，按这个选。"
ABANDON_GRACE_S = 60.0

type StructuredCall = Callable[..., tuple[str, dict[str, object]]]
type FactsReader = Callable[[RunContext, list[TurnObs]], Awaitable[ClaimFacts]]
type PromptReader = Callable[[RunContext], Awaitable[str | None]]


@dataclass
class ScriptResult:
    turns: list[TurnObs] = field(default_factory=list)
    step_unavailable: int | None = None
    infra_error: str | None = None
    users: dict[str, UUID] = field(default_factory=dict)
    current_user: str = "A"
    context: RunContext | None = None
    sessions: list[RunContext] = field(default_factory=list)


class StepUnavailable(Exception):
    """脚本步骤在当前页面上无法执行（卡片/酒店/草稿缺失）。"""


def card_kind(row: ChoiceCardRow) -> str:
    if row.kind == "form" and row.content.get("purpose") == "trip_ask":
        return "trip_ask"
    return row.kind


def group_keys(row: ChoiceCardRow) -> tuple[str, ...]:
    form = row.content.get("form")
    groups = form.get("groups") if isinstance(form, dict) else None
    if not isinstance(groups, list):
        return ()
    return tuple(str(g["key"]) for g in groups if isinstance(g, dict) and "key" in g)


def latest_hotel_segments(
    events: list[RuntimeEvent], fallback_range: tuple[str | None, str | None]
) -> list[dict[str, object]]:
    """最近一次酒店比较展示，按住宿段整理：[{check_in, check_out, cards}]。"""
    for event in reversed(events):
        data = event.presentation.get("data") if event.presentation else None
        if not (isinstance(data, dict) and data.get("component") == "hotel_comparison"):
            continue
        cards = [c for c in data.get("cards") or [] if isinstance(c, dict)]
        segments = data.get("segments")
        if isinstance(segments, list) and segments:
            return [
                {
                    "check_in": s.get("check_in"),
                    "check_out": s.get("check_out"),
                    "cards": [
                        c for c in cards if c.get("evidence_id") in s.get("evidence_ids", [])
                    ],
                }
                for s in segments
                if isinstance(s, dict)
            ]
        return [{"check_in": fallback_range[0], "check_out": fallback_range[1], "cards": cards}]
    return []


def choose_card(cards: list[dict[str, object]], rank: str | int) -> dict[str, object] | None:
    if not cards:
        return None
    if rank == "first":
        return cards[0]
    if rank == "last":
        return cards[-1]
    if isinstance(rank, int):
        return cards[rank] if rank < len(cards) else None
    priced: list[tuple[Decimal, dict[str, object]]] = []
    for card in cards:
        try:
            priced.append((Decimal(str(card["total"])), card))
        except (KeyError, InvalidOperation):
            continue
    return min(priced, key=lambda pair: pair[0])[1] if priced else None


def asks_question(answer: str) -> bool:
    return bool(re.search(r"[？?]", answer[-200:]))


class ScriptRunner:
    def __init__(
        self,
        case: V3Case,
        business: DatabaseEvaluation,
        service: RunService,
        events: dict[UUID, list[RuntimeEvent]],
        *,
        mode: str,
        root: Path,
        prompt_reader: PromptReader,
        structured: StructuredCall | None = None,
        facts_reader: FactsReader | None = None,
    ) -> None:
        self.case, self.business, self.service, self.events = case, business, service, events
        self.mode, self.root, self.prompt_reader = mode, root, prompt_reader
        self.facts_reader = facts_reader
        self.structured = structured  # None=不得调用LLM（离线）
        self.result = ScriptResult()
        self.fresh = False
        self.picks: dict[int, HotelStay] = {}

    @property
    def context(self) -> RunContext:
        assert self.result.context is not None
        return self.result.context

    async def start(self, user_id: UUID, session_id: UUID) -> None:
        self.result.users["A"] = user_id
        self.result.context = RunContext(user_id, session_id)
        self.result.sessions.append(self.result.context)

    async def new_session(self) -> None:
        session = await self.business.sessions.new_session(self.context.user_id)
        self.result.context = RunContext(self.context.user_id, session.session_id)
        self.result.sessions.append(self.result.context)
        self.fresh = True
        self.picks.clear()

    async def switch_user(self, label: str) -> None:
        if label not in self.result.users:
            identity = await self.business.sessions.create_demo_user(
                DemoLogin(display_name=f"v3用户{label}")
            )
            self.result.users[label] = identity.user_id
        self.result.current_user = label
        session = await self.business.sessions.new_session(self.result.users[label])
        self.result.context = RunContext(self.result.users[label], session.session_id)
        self.result.sessions.append(self.result.context)
        self.fresh = True
        self.picks.clear()

    async def run(self) -> ScriptResult:
        try:
            for number, step in enumerate(self.case.user_script, start=1):
                try:
                    if not await self.step(number, step.action, step):
                        break
                except StepUnavailable:
                    self.result.step_unavailable = number
                    break
            if self.result.step_unavailable is None and self.result.infra_error is None:
                await self.extra_turns()
        except ServiceError as error:
            self.result.infra_error = f"service:{error.status}"
        return self.result

    async def step(self, number: int, action: str, step: object) -> bool:
        """返回False=脚本应停止（放弃/基础设施错误）。"""
        assert isinstance(step, Step)
        match action:
            case "say":
                assert step.say is not None
                return await self.submit(step.say)
            case "card":
                assert step.card is not None
                return await self.click_card(step.card, step.say, number)
            case "hotel_pick":
                assert step.hotel_pick is not None
                return await self.pick_hotel(step.hotel_pick)
            case "new_session":
                await self.new_session()
            case "switch_user":
                assert step.switch_user is not None
                await self.switch_user(step.switch_user)
            case "confirm_plan":
                await self.confirm_plan()
        return True

    async def confirm_plan(self) -> None:
        async with transaction(self.business.sessions.database) as db:
            row = await plans.latest_draft(db, self.context)
            draft_id = row.id if row else None
        if draft_id is None:
            raise StepUnavailable
        try:
            await PlanService(self.business.travel).confirm(self.context.user_id, draft_id)
        except ServiceError as error:
            raise StepUnavailable from error

    async def click_card(self, step: CardStep, text: str | None, number: int) -> bool:
        current = await page(self.business, self.context)
        choices = current["choices"]
        assert isinstance(choices, list)
        match = next((c for c in choices if self.matches_kind(c, step.kind)), None)
        if match is None:
            if step.if_missing == "skip":
                return True
            raise StepUnavailable
        options = {o["option_id"] for o in match["options"]}
        option = step.option or match.get("default_option_id") or "confirm"
        if option not in options:
            raise StepUnavailable
        request = await self.business.travel.read_request(self.context)
        selection = ChoiceSelection(
            choice_id=UUID(str(match["choice_id"])), option_id=str(option), answers=step.answers
        )
        return await self.submit(
            text or DEFAULT_CARD_TEXT,
            selection=selection,
            expected_revision=request.revision,
            rejected_is_step=True,
            note=f"点击{step.kind}卡：{option}",
        )

    @staticmethod
    def matches_kind(card: dict[str, object], kind: str) -> bool:
        form = card.get("form")
        purpose = form.get("purpose") if isinstance(form, dict) else None
        if kind == "trip_ask":
            return card.get("kind") == "form" and purpose == "trip_ask"
        if kind == "form":
            return card.get("kind") == "form" and purpose != "trip_ask"
        return card.get("kind") == kind

    async def pick_hotel(self, step: HotelPickStep) -> bool:
        request = await self.business.travel.read_request(self.context)
        flat = [
            e
            for run_events in self.events.values()
            for e in run_events
            if e.context.session_id == self.context.session_id
        ]
        flat.sort(key=lambda e: e.occurred_at)
        segments = latest_hotel_segments(
            flat,
            (
                request.start_date.isoformat() if request.start_date else None,
                request.end_date.isoformat() if request.end_date else None,
            ),
        )
        if step.segment >= len(segments):
            raise StepUnavailable
        cards = segments[step.segment]["cards"]
        assert isinstance(cards, list)
        card = choose_card(cards, step.rank)
        segment = segments[step.segment]
        if card is None or not segment["check_in"] or not segment["check_out"]:
            raise StepUnavailable
        try:
            self.picks[step.segment] = HotelStay(
                check_in=date.fromisoformat(str(segment["check_in"])),
                check_out=date.fromisoformat(str(segment["check_out"])),
                hotel_evidence_id=UUID(str(card["evidence_id"])),
            )
        except (ValueError, KeyError) as error:
            raise StepUnavailable from error
        if len(self.picks) < len(segments):
            return True  # 段未选齐：继续累积，不产生run
        stays = tuple(self.picks[i] for i in sorted(self.picks))
        self.picks.clear()
        return await self.submit(
            DEFAULT_PICK_TEXT,
            hotel_stays=stays,
            expected_revision=request.revision,
            rejected_is_step=True,
            note="选定各段酒店",
        )

    async def extra_turns(self) -> None:
        policy = self.case.fallback
        for _ in range(policy.max_extra_turns):
            if not self.result.turns or not asks_question(self.result.turns[-1].answer):
                return
            text = await self.fallback_text()
            if text is None or not await self.submit(text):
                return

    async def fallback_text(self) -> str | None:
        policy = self.case.fallback.policy
        if policy == "idk":
            return IDK_TEXT
        if policy != "facts" or self.structured is None:
            return None
        payload = {
            "persona": "简短耐心的旅行用户",
            "hidden_goal": "只按hidden_fields如实回答助手的问题；没有的信息就说不知道，不要编造",
            "hidden_fields": self.case.user_facts,
            "dialogue": [
                {"user_turn": t.index, "answer": t.answer} for t in self.result.turns[-4:]
            ],
            "page": {},
            "round": len(self.result.turns) + 1,
            "limit": len(self.case.user_script) + self.case.fallback.max_extra_turns,
        }
        response, _ = await asyncio.to_thread(self.structured, "simulator", payload, self.root)
        try:
            action = UserAction.model_validate_json(response)
        except ValidationError:
            return None
        return action.text if action.kind == "message" else None

    async def submit(
        self,
        text: str,
        *,
        selection: ChoiceSelection | None = None,
        hotel_stays: tuple[HotelStay, ...] | None = None,
        expected_revision: int | None = None,
        rejected_is_step: bool = False,
        note: str = "",
    ) -> bool:
        context = self.context
        message = MessageInput(
            client_message_id=uuid4(),
            text=text,
            mode="offline" if self.mode == "offline" else "deepseek",
            expected_revision=expected_revision,
            selection=selection,
            hotel_stays=hotel_stays,
        )
        try:
            view = await self.service.submit(context.user_id, context.session_id, message)
        except ServiceError as error:
            if rejected_is_step:
                raise StepUnavailable from error
            raise
        run_context = RunContext(context.user_id, context.session_id, view.run_id)
        abandoned = await self.wait(run_context)
        final = await self.service.get(context.user_id, view.run_id)
        async with transaction(self.business.sessions.database) as db:
            row = await runs.owned(db, context.user_id, view.run_id)
            finished = row.finished_at if row else None
            card_rows = list(
                await db.scalars(
                    select(ChoiceCardRow).where(ChoiceCardRow.source_run_id == view.run_id)
                )
            )
        prompt = await self.prompt_reader(run_context) if self.fresh else None
        turn = TurnObs(
            index=len(self.result.turns) + 1,
            user_text=text + (f"（{note}）" if note else ""),
            user=self.result.current_user,
            session_id=str(context.session_id),
            run_id=str(view.run_id),
            status=final.status,
            error_code=final.error_code,
            answer=final.answer,
            created_at=view.created_at,
            finished_at=finished,
            events=tuple(self.events.get(view.run_id, ())),
            cards=tuple(CardObs(card_kind(r), group_keys(r)) for r in card_rows),
            fresh_session=self.fresh,
            prompt_text=prompt,
            abandoned=abandoned,
        )
        self.fresh = False
        if self.facts_reader is not None:
            turn = replace(
                turn, claim_facts=await self.facts_reader(run_context, [*self.result.turns, turn])
            )
        self.result.turns.append(turn)
        self.result.context = run_context
        if abandoned:
            return False
        if final.error_code in {"provider_error", "timeout"}:
            self.result.infra_error = final.error_code
            return False
        return True

    async def wait(self, context: RunContext) -> bool:
        """等run结束；只有题目设了patience_s才会超时取消并记为放弃，默认无限等待
        （profile自带的run超时仍生效，超时的run记为infra_error:timeout）。"""
        task = self.service.tasks.get(context.run_id)
        if task is None:
            return False
        done, _ = await asyncio.wait({task}, timeout=self.case.patience_s)  # None=不限时
        if done:
            return False
        try:
            await self.service.cancel(context.user_id, context.run_id)
        except ServiceError:
            # 取消时run恰好已结束：按“已完成”处理，不是放弃，也不是基础设施错误。
            await asyncio.wait({task}, timeout=ABANDON_GRACE_S)
            return False
        await asyncio.wait({task}, timeout=ABANDON_GRACE_S)
        return True

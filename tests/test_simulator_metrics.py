"""模拟器每轮声明一致性：每轮说法必须由本轮事件支持。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.domain.execution import RunContext, RuntimeEvent
from eval.simulator_metrics import claims_pass, dialogue_claims


def test_cards_in_another_run_cannot_support_this_answer() -> None:
    user, session = uuid4(), uuid4()
    first, second = RunContext(user, session, uuid4()), RunContext(user, session, uuid4())
    events = (
        RuntimeEvent(
            first,
            "presentation",
            presentation={"data": {"component": "choice", "kind": "budget_relaxation"}},
        ),
        RuntimeEvent(second, "text"),
    )
    turns: list[dict[str, object]] = [
        {"status": "completed", "session_id": str(session), "answer": answer, "presentations": []}
        for answer in ("预算确认卡已展示。", "请点击预算确认卡。")
    ]
    claims = dialogue_claims(turns, events)
    assert claims[0]["passed"] is True
    assert claims[1]["card"] is False
    assert claims_pass(claims) is False
    assert claims_pass(dialogue_claims(turns[:1], events)) is None


def test_new_turn_uses_finished_time_and_current_card_expiry_but_old_time_stays_unknown() -> None:
    now = datetime.now(UTC)
    context = RunContext(uuid4(), uuid4(), uuid4())
    events = (
        RuntimeEvent(
            context,
            "presentation",
            presentation={
                "data": {
                    "component": "hotel_comparison",
                    "cards": [{"expires_at": (now + timedelta(minutes=5)).isoformat()}],
                }
            },
        ),
    )
    turn: dict[str, object] = {
        "status": "completed",
        "session_id": str(context.session_id),
        "run_id": str(context.run_id),
        "answer": "报价已过期。",
        "presentations": [],
    }
    assert dialogue_claims([turn], events)[0]["expiry"] is None
    assert dialogue_claims([{**turn, "answered_at": now.isoformat()}], events)[0]["expiry"] is False

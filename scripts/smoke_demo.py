"""经Next同源代理跑三套既有离线业务演示；私有恢复状态不含模型密钥、不调用模型。"""

import argparse
import json
import time
import traceback
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, Field, TypeAdapter

from backend.domain.booking import Booking
from backend.domain.plans import SavedPlan
from backend.services.runs import MessageInput, RunView
from backend.services.sessions import DemoIdentity, SessionView
from backend.services.travel import RequestUpdateView
from backend.services.views import HotelPresentation, PlanView
from scripts.dev import ROOT, configure_environment

BASE = "http://127.0.0.1:3100/api"
STATE = ROOT / ".cache/demo-smoke/state.json"


class State(BaseModel):
    token: str = Field(repr=False)
    session_id: UUID
    plan_id: UUID
    version: int
    booking_id: UUID
    order_id: UUID
    run_ids: tuple[UUID, ...]


def request[T](
    client: httpx.Client, method: str, path: str, model: type[T], body: object = None
) -> T:
    response = client.request(method, path, json=body)
    response.raise_for_status()
    return TypeAdapter(model).validate_python(response.json())


def run_demo(client: httpx.Client, session_id: UUID, command: str) -> RunView:
    body = MessageInput(client_message_id=uuid4(), text=command, mode="offline")
    run = request(
        client, "POST", f"/sessions/{session_id}/messages", RunView, body.model_dump(mode="json")
    )
    deadline = time.monotonic() + 30
    while run.status in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.05)
        run = request(client, "GET", f"/runs/{run.run_id}", RunView)
    assert run.status == "completed", "离线演示未完成"
    assert run.mode == "offline" and run.error_code is None
    print(command + "：通过")
    return run


def presentation[T](run: RunView, model: type[T]) -> T:
    assert len(run.presentations) == 1
    payload = run.presentations[0]["presentation"]
    assert isinstance(payload, dict)
    return TypeAdapter(model).validate_python(payload["data"])


def exercise(client: httpx.Client) -> State:
    owner = request(client, "POST", "/demo/login", DemoIdentity, {"display_name": "离线交付验证"})
    client.headers["Authorization"] = "Bearer " + owner.token
    session = request(client, "POST", "/sessions", SessionView)
    path = f"/sessions/{session.session_id}"
    changed = request(
        client,
        "PATCH",
        path + "/request",
        RequestUpdateView,
        {
            "expected_revision": 0,
            "set": {
                "city": "京都",
                "start_date": "2026-11-03",
                "end_date": "2026-11-05",
                "adults": 2,
                "child_ages": [],
                "rooms": 1,
                "currency": "JPY",
                "budget": "50000",
                "departure_time": "09:00",
                "transport": "walk",
                "hard_constraints": ["住宿：无要求", "房型：无要求", "床型：无要求"],
            },
        },
    )
    assert changed.request.revision == 1
    invalid = client.patch(path + "/request", json={"expected_revision": 0, "set": {"rooms": 2}})
    assert invalid.status_code == 409
    live = client.post(
        path + "/messages",
        json={
            "client_message_id": str(uuid4()),
            "text": "不应产生模型请求",
            "mode": "claude",
        },
    )
    assert live.status_code == 403, f"真实模型模式未被拒绝：status={live.status_code}"

    comparison = run_demo(client, session.session_id, "演示：比较酒店")
    hotels = presentation(comparison, HotelPresentation)
    # 3家酒店 x 每家2张卡（与 tests/integration/test_workbench.py 一致）
    assert len(hotels.cards) == 6 and len({c.hotel_id for c in hotels.cards}) == 3, (
        f"酒店卡数量异常：{len(hotels.cards)}张，预期3家x2张"
    )
    assert hotels.comparison.comparable
    initial = run_demo(client, session.session_id, "演示：生成行程")
    draft = presentation(initial, PlanView)
    assert draft.draft_id and len(draft.cards) == 6 and draft.validation.status == "partial"
    saved = request(client, "POST", f"/plan-drafts/{draft.draft_id}/confirm", SavedPlan)
    assert request(client, "POST", f"/plan-drafts/{draft.draft_id}/confirm", SavedPlan) == saved
    revised = run_demo(client, session.session_id, "演示：修改第二天下午")
    patch = presentation(revised, PlanView)
    assert patch.draft_id and len(patch.changes) == 1
    updated = request(client, "POST", f"/plan-drafts/{patch.draft_id}/confirm", SavedPlan)
    assert (
        updated.version == 2
        and updated.content.hotel_evidence_id == saved.content.hotel_evidence_id
    )
    assert sum(a != b for a, b in zip(saved.content.items, updated.content.items, strict=True)) == 1

    held = request(
        client,
        "POST",
        path + "/hotel-holds",
        Booking,
        {
            "expected_revision": 1,
            "offer_id": str(hotels.cards[0].offer_id),
        },
    )
    assert held.status == "held"
    booked = request(client, "POST", f"/bookings/{held.booking_id}/confirm", Booking)
    again = request(client, "POST", f"/bookings/{held.booking_id}/confirm", Booking)
    assert booked.status == "booked" and booked.order_id and booked.order_id == again.order_id
    other = request(client, "POST", "/demo/login", DemoIdentity, {"display_name": "隔离验证"})
    assert (
        client.get(
            f"/plans/{saved.plan_id}", headers={"Authorization": "Bearer " + other.token}
        ).status_code
        == 404
    )
    return State(
        token=owner.token,
        session_id=session.session_id,
        plan_id=updated.plan_id,
        version=updated.version,
        booking_id=booked.booking_id,
        order_id=booked.order_id,
        run_ids=(comparison.run_id, initial.run_id, revised.run_id),
    )


def verify(client: httpx.Client, state: State) -> None:
    client.headers["Authorization"] = "Bearer " + state.token
    saved = request(client, "GET", f"/plans/{state.plan_id}", PlanView)
    booked = request(client, "GET", f"/bookings/{state.booking_id}", Booking)
    assert saved.version == state.version and booked.status == "booked"
    assert booked.order_id == state.order_id
    for run_id in state.run_ids:
        run = request(client, "GET", f"/runs/{run_id}", RunView)
        assert run.status == "completed" and run.mode == "offline"
        stream = client.get(
            f"/runs/{run_id}/events", headers={"Last-Event-ID": str(run.last_sequence - 1)}
        )
        stream.raise_for_status()
        assert [line for line in stream.text.splitlines() if line.startswith("id:")] == [
            f"id: {run.last_sequence}"
        ]


def locator(error: BaseException) -> str:
    """非敏感失败定位：异常类、HTTP方法+路径+状态码、断言消息与脚本行号；绝不含令牌/头/正文。"""
    parts = [type(error).__name__]
    if isinstance(error, httpx.HTTPStatusError):
        parts.append(
            f"{error.request.method} {error.request.url.path} -> {error.response.status_code}"
        )
    elif isinstance(error, httpx.RequestError):
        parts.append(f"{error.request.method} {error.request.url.path}")
    if isinstance(error, AssertionError) and error.args:
        parts.append(str(error.args[0]))
    frames = traceback.extract_tb(error.__traceback__)
    here = [f for f in frames if f.filename == __file__]
    if here:
        parts.append(f"{here[-1].name}:{here[-1].lineno}")
    return " | ".join(parts)


def main() -> int:
    configure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="只读验证已保存状态，适合重启后运行")
    args = parser.parse_args()
    try:
        with httpx.Client(
            base_url=BASE, timeout=35, trust_env=False, follow_redirects=False
        ) as client:
            state = (
                State.model_validate_json(STATE.read_text(encoding="utf-8"))
                if args.verify
                else exercise(client)
            )
            verify(client, state)
        if not args.verify:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(state.model_dump_json() + "\n", encoding="utf-8", newline="\n")
        print(
            json.dumps(
                {
                    "status": "passed",
                    "mode": "offline",
                    "verification": "read_only" if args.verify else "core_flows",
                }
            )
        )
        return 0
    except (httpx.HTTPError, ValueError, OSError, AssertionError) as error:
        print("failed: 离线交付验证未通过；未输出令牌或原响应，请检查服务与私有状态")
        print("locator: " + locator(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

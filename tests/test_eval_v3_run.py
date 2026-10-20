"""v3运行器的纯逻辑：卡片挑选、预算开关、快照库门槛、取消竞态。"""

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.services.common import ServiceError
from eval.v3_cases import V3Case
from eval.v3_run import build_parser, l1_predictions, main, require_snapshot_database
from eval.v3_user import ScriptRunner, choose_card, effective_answers

EVAL_DSN = "postgresql://u:p@localhost:5432/travel_agent_eval_" + "b" * 32
BASE = {
    "case_id": "unit",
    "category": "memory",
    "title": "t",
    "user_script": [{"say": "a"}, {"new_session": True}, {"say": "b"}],
    "rubric": [{"id": f"r{i}", "q": "q"} for i in range(3)],
}


def case(**changes: Any) -> V3Case:
    return V3Case.model_validate({**BASE, **changes})


def hotel_card(evidence: str, total: Any) -> dict[str, Any]:
    """与HotelOffer.card()/cards()同形：total是字符串或None，evidence_id是字符串。"""
    return {
        "name": "合成酒店",
        "currency": "JPY",
        "total": total,
        "lodging_exceeds_lodging_budget": None,
        "data_mode": "fixture",
        "evidence_id": evidence,
        "source_ref": "fixture:" + evidence,
    }


def test_effective_answers_use_card_defaults_and_script_overrides() -> None:
    card: dict[str, object] = {
        "kind": "form",
        "form": {
            "purpose": "trip_ask",
            "groups": [
                {"key": "pace", "selected": ["relaxed"]},
                {"key": "transport", "selected": []},
                {"key": "wake", "selected": ["w0730"]},
            ],
        },
    }
    assert effective_answers(card, None) == {"pace": ("relaxed",), "wake": ("w0730",)}
    assert effective_answers(card, {"pace": ("intensive",)}) == {
        "pace": ("intensive",),
        "wake": ("w0730",),
    }
    # 非表单卡不组装答案（服务端禁止普通选择混填表单答案）
    assert effective_answers({"kind": "memory_confirm"}, None) is None
    # 表单卡没有预选时给空答案而不是None：trip_ask 允许全不答，None会被服务端422拒绝
    bare: dict[str, object] = {
        "kind": "form",
        "form": {"purpose": "trip_ask", "groups": [{"key": "pace", "selected": []}]},
    }
    assert effective_answers(bare, None) == {}


def test_l1_predictions_derive_update_from_superseded_by() -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    old_id, new_id = uuid4(), uuid4()
    facts = [
        SimpleNamespace(
            id=old_id, key="pace", value="特种兵", scope="long_term", superseded_by=new_id
        ),
        SimpleNamespace(
            id=new_id, key="pace", value="慢节奏", scope="long_term", superseded_by=None
        ),
        SimpleNamespace(
            id=uuid4(), key="transport", value="walk", scope="long_term", superseded_by=None
        ),
    ]
    predictions = l1_predictions(facts)  # type: ignore[arg-type]
    assert [p["op"] for p in predictions] == ["ADD", "UPDATE", "ADD"]
    assert predictions[1]["value"] == "慢节奏"


def test_choose_card_ranks_with_realistic_cards() -> None:
    cards = [
        hotel_card("e1", "24800"),
        hotel_card("e2", None),
        hotel_card("e3", "9800"),
        hotel_card("e4", "100000"),
    ]
    assert choose_card(cards, "first") == cards[0]
    assert choose_card(cards, "last") == cards[3]
    assert choose_card(cards, 2) == cards[2]
    assert choose_card(cards, "cheapest") == cards[2]  # 数字比较，不是字符串比较；None价格跳过
    assert choose_card(cards, 9) is None
    assert choose_card([], "first") is None
    assert choose_card([hotel_card("e1", None)], "cheapest") is None  # 全部未知价：步骤不可用


def test_max_cny_is_optional_and_must_be_positive_when_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只解析参数：绝不调用main()，避免误触发真实运行。"""
    parser = build_parser()
    args = parser.parse_args(["--live"])
    assert args.max_cny is None and args.no_judge is False and args.judge_check is False
    assert parser.parse_args(["--live", "--no-judge", "--judge-check"]).no_judge is True
    # main()在启动任何运行之前就拒绝非正数的上限（参数错误退出码2）
    called: list[str] = []

    def spy(path: Path) -> list[V3Case]:
        called.append("loaded")
        return []

    monkeypatch.setattr("eval.v3_run.load_cases", spy)
    for argv in (["v3", "--max-cny", "0"], ["v3", "--max-cny", "-3"]):
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as raised:
            main()
        assert raised.value.code == 2
    assert called == []


def test_snapshot_database_gate() -> None:
    with_l3 = case(memory={"l3": {"present": ["x"]}})
    without = case()
    require_snapshot_database([with_l3], True, EVAL_DSN)
    require_snapshot_database([with_l3], False, "postgresql://localhost/travel_agent")
    require_snapshot_database([without], True, "postgresql://localhost/travel_agent")
    with pytest.raises(ValueError, match="专用评测库"):
        require_snapshot_database([with_l3], True, "postgresql://localhost/travel_agent")


class RacingService:
    """run在取消请求到达前恰好结束：cancel抛ServiceError。"""

    def __init__(self, task: asyncio.Task[None]) -> None:
        self.tasks = {"run": task}
        self.cancels = 0

    async def cancel(self, user_id: Any, run_id: Any) -> None:
        self.cancels += 1
        raise ServiceError(409, "conflict", "原执行进程已退出")


def test_cancel_race_is_not_abandonment_or_infra_error() -> None:
    async def go() -> tuple[bool, int]:
        task = asyncio.create_task(asyncio.sleep(0.2))
        service = RacingService(task)
        runner = ScriptRunner(
            case().model_copy(update={"patience_s": 0.05}),
            None,  # type: ignore[arg-type]
            service,  # type: ignore[arg-type]
            {},
            mode="offline",
            root=None,  # type: ignore[arg-type]
            prompt_reader=None,  # type: ignore[arg-type]
        )
        context = type("C", (), {"run_id": "run", "user_id": 1})()
        return await runner.wait(context), service.cancels

    abandoned, cancels = asyncio.run(go())
    assert abandoned is False and cancels == 1


def test_live_is_refused_under_pytest_and_loads_no_cases(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """pytest进程里的--live一律退出码2，且在读题库之前；显式放行变量才可绕过。"""
    from eval import simulator

    loaded: list[str] = []

    def spy(path: Path) -> list[V3Case]:
        loaded.append("loaded")
        return []

    monkeypatch.setattr("eval.v3_run.load_cases", spy)
    monkeypatch.delenv("TRAVEL_ALLOW_LIVE_IN_TESTS", raising=False)
    assert "PYTEST_CURRENT_TEST" in __import__("os").environ
    with pytest.raises(SystemExit) as raised:
        main(["--live"])
    assert raised.value.code == 2 and loaded == []
    assert "TRAVEL_ALLOW_LIVE_IN_TESTS" in capsys.readouterr().err
    with pytest.raises(SystemExit) as sim:
        simulator.main(["--live"])
    assert sim.value.code == 2
    # 非live的离线调用不受影响（simulator离线只打印准备数量）
    assert simulator.main([]) == 0

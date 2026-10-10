"""离线守卫：smoke_demo 校验响应所用模型必须等于 FastAPI 路由声明的返回模型，防止契约漂移。"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.routing import APIRoute

from backend.api.app import create_app
from backend.services.travel import RequestUpdate
from scripts import smoke_demo

ROOT = Path(__file__).resolve().parents[1]


def render(node: ast.expr, names: dict[str, str]) -> str:
    """把 smoke_demo 里的路径表达式还原成路由模板；插值统一为 {x}。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            str(part.value) if isinstance(part, ast.Constant) else "{x}" for part in node.values
        )
    if isinstance(node, ast.Name):
        return names[node.id]
    assert isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add), ast.dump(node)
    return render(node.left, names) + render(node.right, names)


def smoke_calls(source: str) -> list[tuple[str, str, str]]:
    """提取每个 request(client, METHOD, path, Model, ...) 调用；任何无法解析的调用都按行号报错。"""
    tree = ast.parse(source)
    names: dict[str, str] = {}
    calls: list[tuple[str, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.JoinedStr):
            if isinstance(node.targets[0], ast.Name):
                names[node.targets[0].id] = render(node.value, names)
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "request"
        ):
            continue
        args = node.args
        parsable = (
            not node.keywords
            and len(args) >= 4
            and isinstance(args[1], ast.Constant)
            and isinstance(args[3], ast.Name)
        )
        assert parsable, f"第{node.lineno}行 request(...) 调用无法被契约守卫解析，请更新守卫"
        calls.append((str(args[1].value), render(args[2], names), args[3].id))  # type: ignore[attr-defined]
    return calls


def declared() -> dict[tuple[str, str], object]:
    app = create_app(MagicMock(), runs_service=MagicMock(), booking_service=MagicMock())
    return {
        (method, re.sub(r"\{[^}]+\}", "{x}", route.path)): route.response_model
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods or ()
    }


def test_smoke_demo_models_match_declared_route_models() -> None:
    routes = declared()
    calls = smoke_calls((ROOT / "scripts/smoke_demo.py").read_text(encoding="utf-8"))
    assert len(calls) >= 15
    for method, path, model_name in calls:
        key = (method, path)
        assert key in routes, f"smoke_demo 调用了不存在的路由 {key}"
        assert routes[key] is getattr(smoke_demo, model_name), (
            f"{method} {path}: smoke_demo 用 {model_name}，路由声明 {routes[key]}"
        )


def test_guard_rejects_old_request_update_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smoke_demo, "RequestUpdateView", RequestUpdate)
    with pytest.raises(AssertionError, match="RequestUpdateView"):
        test_smoke_demo_models_match_declared_route_models()


@pytest.mark.parametrize(
    "call",
    [
        'request(client, "GET", "/runs/1", model=RunView)',
        'request(client, "GET", "/runs/1")',
        'request(client, method, "/runs/1", RunView)',
        'request(client, "GET", "/runs/1", mod.RunView)',
    ],
)
def test_guard_fails_on_unparseable_request_call(call: str) -> None:
    with pytest.raises(AssertionError, match="第2行"):
        smoke_calls("\n" + call)


def test_guard_parses_well_formed_request_call() -> None:
    source = 'path = f"/runs/{rid}"\nrequest(client, "GET", path, RunView)'
    assert smoke_calls(source) == [("GET", "/runs/{x}", "RunView")]

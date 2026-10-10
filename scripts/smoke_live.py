"""显式执行一个城市的一轮真实API/SDK规划；只保存引用和状态，不录制供应商详情。"""

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
from dotenv import load_dotenv
from sqlalchemy import select, text

from backend.persistence.database import Database, configuration, database_url
from backend.persistence.models import RunEventRow
from backend.providers.claude_agent.live import runtime_budget
from backend.providers.claude_agent.settings import load_runtime_settings
from backend.services.runs import MessageInput, RunView
from backend.services.sessions import DemoIdentity, SessionView
from backend.services.travel import RequestUpdate
from scripts.dev import ROOT, configure_environment
from scripts.smoke_demo import request


@dataclass(frozen=True)
class Counters:
    apis: dict[str, int]
    model_requests: int
    accounted: Decimal
    tools: tuple[dict[str, object], ...]


def counters(run_id: UUID | None = None) -> Counters:
    async def read() -> tuple[dict[str, int], tuple[dict[str, object], ...]]:
        database = Database(database_url(configuration()))
        try:
            async with database.sessions() as db:
                counts = await db.execute(
                    text(
                        "SELECT api,calls FROM external_api_usage "
                        "WHERE day=(now() AT TIME ZONE 'UTC')::date"
                    )
                )
                apis = {str(row[0]): int(row[1]) for row in counts}
                rows = (
                    await db.scalars(select(RunEventRow).where(RunEventRow.run_id == run_id))
                    if run_id
                    else ()
                )
                tools = tuple(
                    {"name": row.payload.get("tool_name"), "code": row.payload.get("code")}
                    for row in rows
                    if row.payload.get("kind") == "tool_finished"
                )
                return apis, tools
        finally:
            await database.close()

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        apis, tools = runner.run(read())
    settings = load_runtime_settings({**os.environ, "LLM_PROVIDER": "deepseek"})
    requests, charge = runtime_budget(ROOT, settings).totals()
    return Counters(apis, requests, charge, tools)


def exercise(client: httpx.Client, city: str, start: date) -> dict[str, object]:
    before = counters()
    identity = request(client, "POST", "/demo/login", DemoIdentity, {"display_name": "V2城市验收"})
    client.headers["Authorization"] = "Bearer " + identity.token
    session = request(client, "POST", "/sessions", SessionView)
    path = f"/sessions/{session.session_id}"
    request(
        client,
        "PATCH",
        path + "/request",
        RequestUpdate,
        {
            "expected_revision": 0,
            "set": {
                "city": city,
                "start_date": start.isoformat(),
                "end_date": (start + timedelta(days=2)).isoformat(),
                "adults": 2,
                "child_ages": [],
                "rooms": 1,
                "currency": "JPY",
                "budget": "60000",
                "departure_time": "09:00",
                "transport": "walk",
            },
        },
    )
    text = (
        f"请按已填写的{city}条件比较两家酒店并生成三天行程。"
        "先读取business_context；酒店搜索一次，景点只搜索一次取4个，天气查询一次。"
        "第一天排两个距离较近的景点，查这两点的步行路线；第二和第三天各一个景点。"
        "景点详情复用本轮已有结果，不重复搜索。用工具校验、暂存并展示酒店卡片和行程草稿。"
        "无法核实的费用和开放信息保持未知，不虚构。最后给出简洁旅行方案。"
    )
    body = MessageInput(client_message_id=uuid4(), text=text, mode="deepseek")
    run = request(client, "POST", path + "/messages", RunView, body.model_dump(mode="json"))
    deadline = time.monotonic() + 170
    while run.status in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(1)
        run = request(client, "GET", f"/runs/{run.run_id}", RunView)
    # 不调用详情读取接口：避免为验证重复消耗 Places 配额。
    presentations = [item.get("presentation") for item in run.presentations]
    references: list[dict[str, object]] = []
    for item in presentations:
        if isinstance(item, dict) and isinstance(item.get("data"), dict):
            data = item["data"]
            references.append(
                {key: value for key, value in data.items() if key in {"draft_id", "component"}}
            )
    after = counters(run.run_id)
    result: dict[str, object] = {
        "city": city,
        "run_id": str(run.run_id),
        "session_id": str(session.session_id),
        "status": run.status,
        "error_code": run.error_code,
        "has_answer": bool(run.answer.strip()),
        "presentations": references,
        "tools": after.tools,
        "api_call_delta": {
            api: count - before.apis.get(api, 0) for api, count in after.apis.items()
        },
        "model_http_delta": after.model_requests - before.model_requests,
        "model_cost_cny_upper_bound": str(after.accounted - before.accounted),
    }
    output = ROOT / ".cache/v2-verification" / f"{city}-{run.run_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if run.status != "completed" or run.error_code or not run.answer.strip():
        raise ValueError("真实流程未完整完成；保留运行记录，不自动重跑")
    if not any(item.get("draft_id") for item in references):
        raise ValueError("未生成行程草稿；保留运行记录，不自动重跑")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="明确允许本次真实付费调用")
    parser.add_argument("--city", required=True, choices=("大阪", "札幌", "那霸", "箱根"))
    parser.add_argument(
        "--start", type=date.fromisoformat, default=date.today() + timedelta(days=9)
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:3000/api")
    args = parser.parse_args()
    if not args.execute:
        parser.error("必须显式 --execute；禁止循环或CI运行")
    configure_environment()
    load_dotenv(ROOT / ".env", encoding="utf-8")
    try:
        with httpx.Client(base_url=args.base_url, timeout=35, trust_env=False) as client:
            exercise(client, args.city, args.start)
        return 0
    except (httpx.HTTPError, ValueError, OSError):
        print("failed: 请检查已保存的run状态和服务日志，不输出密钥或原始响应")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

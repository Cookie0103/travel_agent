"""显式本地DeepSeek → PG → Langfuse v4联验；只输出白名单元数据。"""

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from dotenv import load_dotenv
from pydantic import TypeAdapter
from sqlalchemy import select

from backend.adapters.tracing import cloud_configuration, push_scores
from backend.persistence.database import Database, configuration, database_url
from backend.persistence.models import TaskRunRow
from backend.services.runs import MessageInput, RunView
from backend.services.sessions import DemoIdentity, SessionView
from scripts.dev import ROOT
from scripts.smoke_demo import request
from scripts.smoke_live import counters


def anchor(run_id: UUID) -> str:
    async def read() -> str:
        database = Database(database_url(configuration()))
        try:
            async with database.sessions() as db:
                value = await db.scalar(select(TaskRunRow.trace_id).where(TaskRunRow.id == run_id))
                if not value:
                    raise ValueError("PG trace锚点缺失")
                return value
        finally:
            await database.close()

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(read())


def cloud_rows(client: httpx.Client, path: str, params: dict[str, str]) -> list[dict[str, object]]:
    """不读取io字段，不打印上游错误正文；单轮有界请求。"""
    response = client.get(path, params=params)
    if not response.is_success:
        raise ValueError(f"Langfuse读取失败：HTTP {response.status_code}")
    payload = TypeAdapter(dict[str, object]).validate_python(response.json())
    return TypeAdapter(list[dict[str, object]]).validate_python(payload.get("data", []))


def local_measurement(path: Path) -> tuple[int, str]:
    rows = [
        TypeAdapter(dict[str, object]).validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    sdk = [row for row in rows if row.get("name") == "agent.sdk"]
    if len(sdk) != 1:
        raise ValueError("本轮SDK trace尚未完整写入")
    attributes = TypeAdapter(dict[str, object]).validate_python(sdk[0].get("attributes"))
    attempts, charge = (
        attributes.get("travel.http_attempts"),
        attributes.get("travel.run_accounted"),
    )
    if (
        type(attempts) is not int
        or not isinstance(attempts, int)
        or attempts < 1
        or attributes.get("travel.currency") != "CNY"
        or not isinstance(charge, str)
        or not Decimal(charge).is_finite()
        or Decimal(charge) < 0
    ):
        raise ValueError("本轮计费证据缺失")
    return attempts, charge


def exercise() -> int:
    load_dotenv(ROOT / ".env")
    base, public, secret = cloud_configuration(os.environ)
    before = counters()
    started = datetime.now(UTC)
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as local:
        identity = request(local, "POST", "/demo/login", DemoIdentity, {"display_name": "合成联验"})
        local.headers["Authorization"] = "Bearer " + identity.token
        session = request(local, "POST", "/sessions", SessionView)
        body = MessageInput(
            client_message_id=uuid4(),
            mode="deepseek",
            text=(
                "我要去京都。先读取上下文，只展示标准、特种兵、比较轻松的节奏选择卡。"
                "日期和人数未知，不查询任何供应商，不生成、保存或预订行程。"
            ),
        )
        run = request(
            local,
            "POST",
            f"/sessions/{session.session_id}/messages",
            RunView,
            body.model_dump(mode="json"),
        )
        deadline = time.monotonic() + 170
        while run.status in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(1)
            run = request(local, "GET", f"/runs/{run.run_id}", RunView)
    if run.status != "completed" or run.error_code:
        raise ValueError("真实run未成功；不自动重新付费")
    trace_id = anchor(run.run_id)
    after = counters(run.run_id)
    trace_path = (
        ROOT
        / ".cache/api-traces"
        / str(identity.user_id)
        / str(session.session_id)
        / f"{run.run_id}.jsonl"
    )
    deadline = time.monotonic() + 10
    while not trace_path.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    attempts, charge = local_measurement(trace_path)
    expected_session = hmac.new(
        (os.environ.get("TRAVEL_TRACE_HMAC_KEY") or secret).encode(),
        f"session:{session.session_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    parameters = {
        "traceId": trace_id,
        "fields": "core,basic,trace_context,metadata",
        "limit": "1000",
        "fromStartTime": (started - timedelta(minutes=1)).isoformat(),
        "toStartTime": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    }
    with httpx.Client(base_url=base, auth=(public, secret), timeout=10) as cloud:
        deadline = time.monotonic() + 50
        observations: list[dict[str, object]] = []
        while time.monotonic() < deadline:
            observations = cloud_rows(cloud, "/api/public/v2/observations", parameters)
            if len(observations) >= len(after.tools) + 2 + attempts:
                break
            time.sleep(2)
        tool_count = sum(str(row.get("name", "")).startswith("tool.") for row in observations)
        model_count = sum(row.get("name") == "gen_ai.chat" for row in observations)
        if not observations or tool_count != len(after.tools):
            raise ValueError("云端工具数与PG事件不一致")
        if model_count != attempts:
            raise ValueError("云端模型请求数与实际计费请求不一致")
        if not all(row.get("sessionId") == expected_session for row in observations):
            raise ValueError("云端session假名不一致")
        if not all(
            "deepseek" in TypeAdapter(list[str]).validate_python(row.get("tags", []))
            for row in observations
        ):
            raise ValueError("云端tags缺失")
        if any("input" in row or "output" in row for row in observations):
            raise ValueError("联验不应读取正文")
        if not push_scores(trace_id, {"linkage_smoke": 1.0}, http=cloud):
            raise ValueError("测试分数未推送")
        deadline = time.monotonic() + 30
        scores: list[dict[str, object]] = []
        while time.monotonic() < deadline:
            scores = cloud_rows(
                cloud,
                "/api/public/v3/scores",
                {
                    "traceId": trace_id,
                    "name": "linkage_smoke",
                    "limit": "10",
                    "fromTimestamp": started.isoformat(),
                    "toTimestamp": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
                },
            )
            if any(row.get("value") == 1 for row in scores):
                break
            time.sleep(2)
        if not any(row.get("value") == 1 for row in scores):
            raise ValueError("测试分数未读回")
    evidence = {
        "verification": "VERIFIED",
        "date": datetime.now(UTC).isoformat(),
        "run_id": str(run.run_id),
        "trace_id": trace_id,
        "status": run.status,
        "session_hmac": expected_session,
        "tags": observations[0].get("tags"),
        "pg_tool_events": len(after.tools),
        "cloud_tool_spans": tool_count,
        "model_http_attempts": attempts,
        "cloud_model_spans": model_count,
        "score_read_back": True,
        "model_cost_cny": charge,
        "account_http_delta": after.model_requests - before.model_requests,
        "account_cost_cny_delta": str(after.accounted - before.accounted),
        "api_call_delta": {k: v - before.apis.get(k, 0) for k, v in after.apis.items()},
        "body_exported": False,
        "body_read": False,
    }
    target = ROOT / "docs/evidence/t6-langfuse-linkage-2026-10-13.json"
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--trace-cloud", action="store_true")
    args = parser.parse_args()
    if not (args.live and args.trace_cloud):
        return 2
    try:
        return exercise()
    except (ValueError, httpx.HTTPError):
        print("联验失败；检查本地脱敏日志，不自动重复付费。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

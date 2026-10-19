"""P-72：显式授权后单轮真实模型、合成离线事实；默认仅检查合成输入。"""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError

from backend.domain.catalog import Place
from backend.domain.evidence import EvidenceRecord, evidence_conditions
from backend.domain.execution import RunContext
from backend.domain.travel_request import RequestPatch
from backend.limits import ProbeError, read_budget
from backend.persistence.database import configuration, database_url
from backend.providers.claude_agent.live import run_live
from backend.services.hotels import HotelService
from backend.services.sessions import DemoLogin, SessionService
from backend.services.travel import TravelService
from data.import_catalog import load_snapshot
from scripts.dev import ROOT


def synthetic_places() -> tuple[Place, ...]:
    originals = [p for p in load_snapshot() if isinstance(p, Place)][:2]
    ref = "fixture:P72-feedback"
    return tuple(
        Place.model_validate(
            {
                **p.model_dump(mode="json"),
                "name": f"P72合成诊断地点{index + 1}（非真实营业资料）",
                "opening_hours": "09:00-17:00",
                "source": {
                    **p.source.model_dump(mode="json"),
                    "source_ref": ref,
                    "content_version": "p72-synthetic-v1",
                    "attribution": "人工合成诊断",
                },
                "field_sources": {**p.field_sources, "name": ref, "opening_hours": ref},
            }
        )
        for index, p in enumerate(originals)
    )


def summarize(
    report: dict[str, object], traces: list[dict[str, object]] | None = None
) -> dict[str, object]:
    closed = repaired = presented = False
    stage_id = None
    ends = [t for t in traces or [] if t.get("ev") == "tool_end"]
    sequence = []
    for trace in ends:
        detail = trace.get("detail")
        details = [v for v in detail if isinstance(v, str)] if isinstance(detail, list) else []
        sequence.append({"tool": trace.get("name"), "code": trace.get("code"), "detail": details})
    cursor = 0
    aligned = True
    events = report.get("events", [])
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        if event.get("kind") == "tool_finished":
            if cursor >= len(ends) or (
                ends[cursor].get("name") != event.get("tool_name")
                or ends[cursor].get("code") != event.get("code")
            ):
                aligned = False
                break  # 缺日志或顺序不一致时不猜对应关系。
            trace = ends[cursor]
            cursor += 1
            detail = trace.get("detail")
            details = detail if isinstance(detail, list) else []
            if event.get("tool_name") == "validate_itinerary" and event.get("code") is None:
                if any(
                    isinstance(v, str) and v.startswith("opening_hours:conflict") for v in details
                ):
                    closed = True
                    repaired = presented = False
                    stage_id = None
                elif closed and any(v in ("report:partial", "report:complete") for v in details):
                    repaired = True
            business = event.get("business_result")
            if (
                repaired
                and event.get("tool_name") == "stage_plan_change"
                and event.get("code") is None
                and isinstance(business, dict)
                and business.get("kind") == "draft_staged"
                and business.get("validation_status") in {"complete", "partial"}
            ):
                stage_id = business.get("draft_id")
        presentation = event.get("presentation")
        data = presentation.get("data") if isinstance(presentation, dict) else None
        if (
            event.get("kind") == "presentation"
            and isinstance(data, dict)
            and stage_id is not None
            and data.get("draft_id") == stage_id
            and data.get("status") == "staged"
        ):
            validation = data.get("validation")
            presented = isinstance(validation, dict) and validation.get("status") in {
                "complete",
                "partial",
            }
    return {
        "status": report.get("status"),
        "code": report.get("code"),
        "http_attempts": report.get("http_attempts"),
        "run_accounted_cny": report.get("run_accounted_cny"),
        "closed_conflict_observed": closed,
        "subsequent_validation_repaired": repaired,
        "draft_staged": stage_id is not None,
        "same_draft_presented": presented,
        "event_trace_aligned": aligned and cursor == len(ends),
        "feedback_repaired": report.get("status") == "success"
        and aligned
        and cursor == len(ends)
        and closed
        and repaired
        and stage_id is not None
        and presented,
        "tools": sequence,
    }


def diagnostic_request() -> RequestPatch:
    return RequestPatch.model_validate(
        {
            "expected_revision": 0,
            "set": {
                "city": "京都",
                "hotel_search_location": "京都",
                "start_date": "2026-11-03",
                "end_date": "2026-11-04",
                "adults": 1,
                "child_ages": [],
                "rooms": 1,
                "transport": "walk",
                "soft_constraints": ["节奏：标准"],
                "departure_time": "09:00",
                "budget": "50000",
                "currency": "JPY",
                "hard_constraints": ["住宿：独立房间", "房型：禁烟", "床型：无要求"],
            },
        }
    )


async def prepare() -> tuple[RunContext, str, str]:
    sessions = SessionService(database_url(configuration()), demo_enabled=True)
    try:
        identity = await sessions.create_demo_user(DemoLogin(display_name="P72合成反馈诊断"))
        session = await sessions.new_session(identity.user_id)
        context = RunContext(identity.user_id, session.session_id)
        travel = TravelService(sessions.database)
        await travel.patch_request(context, diagnostic_request())
        request = await travel.get_request(context)
        now = datetime.now(UTC)
        records = tuple(
            EvidenceRecord(
                entity_id=p.place_id,
                field_path="catalog",
                value=p.model_dump(mode="json"),
                kind="place",
                request_revision=request.revision,
                conditions=evidence_conditions(request, "place"),
                provider="test-fixture",
                source_ref="fixture:P72-feedback",
                content_version="p72-synthetic-v1",
                retrieved_at=now,
                valid_until=now + timedelta(hours=1),
                data_mode="fixture",
            )
            for p in synthetic_places()
        )
        await travel.record_evidence(context, records)
        hotels = await HotelService(travel).search(context, request.revision, limit=1)
        assert hotels, "合成酒店资料不可用，未调用模型"
        items = [
            {"place_evidence_id": str(records[i % 2].evidence_id), "start": start, "end": end}
            for i, (start, end) in enumerate(
                (
                    ("2026-11-03T09:00:00+09:00", "2026-11-03T10:00:00+09:00"),
                    ("2026-11-03T18:00:00+09:00", "2026-11-03T19:00:00+09:00"),
                    ("2026-11-04T09:00:00+09:00", "2026-11-04T10:00:00+09:00"),
                    ("2026-11-04T11:00:00+09:00", "2026-11-04T12:00:00+09:00"),
                )
            )
        ]
        proposal = {
            "expected_revision": request.revision,
            "items": items,
            "hotel_evidence_id": str(hotels[0].evidence_id),
        }
        prompt = (
            "这是授权的一次人工合成诊断，非真实旅行事实。两地点营业均为09:00-17:00；"
            "住宿报价与地点证据已在本会话发布，不需重复搜索。请首先用validate_itinerary校验下列"
            "故意含闭馆错误的原草案一次，不要先修正。随后依据工具反馈修复所有硬冲突，"
            "用现有证据重估受影响相邻路线，重新校验同一最终候选，stage_plan_change暂存并"
            "present_travel_result展示草稿；保留unknown和密度/重复警告，不确认、不暂留、不下单。"
            "只诊断这些合成项，不增加真实景点或调用任何真实旅行API。原草案："
            + json.dumps(proposal, ensure_ascii=False)
        )
        return context, prompt, sessions.database.engine.url.render_as_string(hide_password=False)
    finally:
        await sessions.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="用户授权后仅执行一轮DeepSeek")
    args = parser.parse_args()
    if not args.live:
        print("offline-input-check: synthetic_places=2, hours=09:00-17:00, real_calls=0")
        assert len(synthetic_places()) == 2
        diagnostic_request()
        return 0
    marker = ROOT / ".cache" / "p72-feedback-probe.started"
    if marker.exists():
        print("模型探针已有一次执行记录；不自动重跑，请先核对原结果。")
        return 1
    try:
        load_dotenv(ROOT / ".env", encoding="utf-8")
        os.environ["TRAVEL_PROFILE"] = "default"
        # 只降低该探针子进程的日预算；不修改.env/现有服务。
        os.environ["DAILY_BUDGET_CNY"] = str(
            min(read_budget(os.environ.get("DAILY_BUDGET_CNY", "")), 15)
        )
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            context, prompt, dsn = runner.run(prepare())
        marker.parent.mkdir(exist_ok=True)
        with marker.open("x", encoding="utf-8") as stream:
            stream.write(str(context.run_id)[:8] + "\n")
        report = run_live(
            prompt,
            context,
            ROOT,
            database_dsn=dsn,
            provider="deepseek",
            real_data=False,
            max_attempts=12,
        )
        directory = ROOT / ".cache" / "sessions" / str(context.user_id) / str(context.session_id)
        traces = [
            json.loads(line.removeprefix("TRACE "))
            for line in (directory / f"trace-{context.run_id}.jsonl").read_text().splitlines()
        ]
        result = summarize(report, traces)
        result["run"] = str(context.run_id)[:8]
        (ROOT / ".cache" / "p72-feedback-summary.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (SQLAlchemyError, ProbeError, OSError, ValueError) as error:
        print(json.dumps({"probe_stopped": type(error).__name__, "real_travel_calls": 0}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

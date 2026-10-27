"""工作包D审查回归：草稿过期后的幂等重放、锁定与日历的HTTP契约、统一错误格式、锁与待确认草稿。"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL, func, select

from backend.api.app import create_app
from backend.domain.execution import RunContext
from backend.domain.plans import PlanDraft, SavedPlan, StageInput
from backend.domain.travel_request import RequestPatch
from backend.persistence.models import (
    BusinessOperationRow,
    EvidenceRow,
    PlanDraftRow,
    PlanRow,
)
from backend.services.common import ServiceError, transaction
from backend.services.plans import LockInput, PlanService
from backend.services.sessions import DemoLogin, SessionService
from backend.services.travel import TravelService
from backend.tools.travel import TravelToolExecutor
from tests.integration.test_plans import initial_draft, patch_stage
from tests.runner import SELECTOR_OPTIONS, selector_runner

pytestmark = pytest.mark.integration

Env = tuple[asyncio.Runner, TravelService, RunContext, TestClient, dict[str, str]]


@pytest.fixture
def env(postgres_url: URL) -> Iterator[Env]:
    with selector_runner() as runner:
        sessions = SessionService(postgres_url, demo_enabled=True)
        identity = runner.run(sessions.create_demo_user(DemoLogin()))
        session = runner.run(sessions.new_session(identity.user_id))
        context = RunContext(identity.user_id, session.session_id)
        travel = TravelService(sessions.database)
        runner.run(
            travel.patch_request(
                context,
                RequestPatch.model_validate(
                    {
                        "expected_revision": 0,
                        "set": {
                            "city": "京都",
                            "adults": 2,
                            "child_ages": [],
                            "rooms": 1,
                            "hard_constraints": ["住宿：无要求", "房型：无要求", "床型：无要求"],
                            "start_date": "2026-11-03",
                            "end_date": "2026-11-05",
                        },
                    }
                ),
            )
        )
        app = create_app(SessionService(postgres_url, demo_enabled=True))
        with TestClient(app, backend_options=SELECTOR_OPTIONS) as client:
            yield runner, travel, context, client, {"Authorization": "Bearer " + identity.token}
        runner.run(sessions.close())


def initial_args(draft: PlanDraft) -> StageInput:
    proposal = draft.content.proposal(draft.request_revision)
    return StageInput.model_validate(
        {"change": {"kind": "initial", "proposal": proposal.model_dump(mode="json")}}
    )


async def expire_draft(travel: TravelService, context: RunContext, draft: PlanDraft) -> None:
    """让草稿及其幂等缓存同时过期，等价于10分钟后。"""
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    async with transaction(travel.database) as db:
        row = await db.get(PlanDraftRow, draft.draft_id)
        assert row is not None
        row.payload = row.payload | {"expires_at": past}
        for cached in await db.scalars(
            select(BusinessOperationRow).where(
                BusinessOperationRow.session_id == context.session_id,
                BusinessOperationRow.name == "stage_plan",
            )
        ):
            cached.payload = cached.payload | {"expires_at": past}


async def stale_evidence(travel: TravelService, evidence_id: UUID, name: str | None = None) -> None:
    async with transaction(travel.database) as db:
        row = await db.get(EvidenceRow, evidence_id)
        assert row is not None
        value = row.payload["value"]
        assert isinstance(value, dict)
        row.payload = row.payload | {
            "retrieved_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            "valid_until": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            **({"value": value | {"name": name}} if name else {}),
        }


async def draft_count(travel: TravelService, plan_id: UUID) -> int:
    async with transaction(travel.database) as db:
        return (
            await db.scalar(
                select(func.count())
                .select_from(PlanDraftRow)
                .where(PlanDraftRow.plan_id == plan_id)
            )
            or 0
        )


async def confirmed(travel: TravelService, context: RunContext) -> SavedPlan:
    return await PlanService(travel).confirm(
        context.user_id, (await initial_draft(travel, context)).draft_id
    )


# ---- D1：草稿过期后用相同参数重新暂存 ----


def test_restaging_the_same_arguments_after_expiry_makes_a_new_draft_and_keeps_replay_idempotent(
    env: Env,
) -> None:
    runner, travel, context, _, _ = env
    service = PlanService(travel)

    async def exercise() -> None:
        old = await initial_draft(travel, context)
        args = initial_args(old)
        assert (await service.stage(context, args)).draft_id == old.draft_id  # 未过期：同一草稿
        await expire_draft(travel, context, old)
        fresh = await service.stage(context, args)
        assert fresh.draft_id != old.draft_id and fresh.plan_id == old.plan_id
        assert fresh.expires_at > datetime.now(UTC) and fresh.validation.status != "conflict"
        again = await service.stage(context, args)  # 新草稿同样可幂等重放
        assert again.draft_id == fresh.draft_id and await draft_count(travel, old.plan_id) == 2
        old_view = await service.get_draft(context.user_id, old.draft_id)
        assert old_view["expired"] is True and old_view["status"] == "staged"
        with pytest.raises(ServiceError) as expired:
            await service.confirm(context.user_id, old.draft_id)
        assert expired.value.status == 409 and expired.value.reason == "draft_expired"
        assert (await service.confirm(context.user_id, fresh.draft_id)).version == 1

    runner.run(exercise())


def test_restaging_an_expired_patch_after_it_was_cached_makes_a_new_draft(env: Env) -> None:
    runner, travel, context, _, _ = env
    service = PlanService(travel)

    async def exercise() -> None:
        saved = await confirmed(travel, context)
        args = patch_stage(saved)
        old = await service.stage(context, args)
        await expire_draft(travel, context, old)
        fresh = await service.stage(context, args)
        assert fresh.draft_id != old.draft_id and fresh.base_version == saved.version
        assert (await service.confirm(context.user_id, fresh.draft_id)).version == 2

    runner.run(exercise())


def test_parallel_restage_after_expiry_creates_exactly_one_new_draft(env: Env) -> None:
    runner, travel, context, _, _ = env
    service = PlanService(travel)

    async def exercise() -> None:
        old = await initial_draft(travel, context)
        await expire_draft(travel, context, old)
        first, second = await asyncio.gather(
            service.stage(context, initial_args(old)), service.stage(context, initial_args(old))
        )
        assert first.draft_id == second.draft_id != old.draft_id
        assert await draft_count(travel, old.plan_id) == 2

    runner.run(exercise())


def test_restaging_after_expiry_with_expired_evidence_says_to_requery_and_changes_nothing(
    env: Env,
) -> None:
    runner, travel, context, _, _ = env
    service = PlanService(travel)

    async def exercise() -> None:
        old = await initial_draft(travel, context)
        args = initial_args(old)
        await expire_draft(travel, context, old)
        await stale_evidence(travel, old.content.items[0].place_evidence_id)
        with pytest.raises(ServiceError) as failed:
            await service.stage(context, args)
        assert failed.value.status == 409 and (failed.value.reason or "").startswith(
            "evidence_stale"
        )
        assert "重新" in str(failed.value) and await draft_count(travel, old.plan_id) == 1

    runner.run(exercise())


# ---- D2：锁定接口（服务层 + HTTP） ----


def test_lock_rejects_a_stale_expected_version_without_changing_the_plan(env: Env) -> None:
    runner, travel, context, _, _ = env
    service = PlanService(travel)

    async def exercise() -> None:
        saved = await confirmed(travel, context)
        first, second = saved.content.items[0].item_id, saved.content.items[1].item_id
        locked = await service.locks(
            context.user_id, saved.plan_id, LockInput(expected_version=1, locked_item_ids=(first,))
        )
        assert locked.version == 2
        with pytest.raises(ServiceError) as stale:  # 调用方仍以为是第1版
            await service.locks(
                context.user_id,
                saved.plan_id,
                LockInput(expected_version=1, locked_item_ids=(second,)),
            )
        assert stale.value.status == 409 and stale.value.reason == "plan_version_changed"
        current = await service.get(context.user_id, saved.plan_id)
        assert current["version"] == 2
        cards = current["cards"]
        assert isinstance(cards, list) and [c["locked"] for c in cards] == [True, False]

    runner.run(exercise())


@pytest.mark.parametrize("fault", ["unknown", "duplicate"])
def test_lock_rejects_unknown_or_duplicate_item_ids(env: Env, fault: str) -> None:
    runner, travel, context, _, _ = env

    async def exercise() -> None:
        saved = await confirmed(travel, context)
        known = saved.content.items[0].item_id
        ids = (uuid4(),) if fault == "unknown" else (known, known)
        with pytest.raises(ServiceError) as failed:
            await PlanService(travel).locks(
                context.user_id, saved.plan_id, LockInput(expected_version=1, locked_item_ids=ids)
            )
        assert failed.value.status == 422 and failed.value.reason == "lock_invalid"

    runner.run(exercise())


def test_locks_http_contract(env: Env) -> None:
    runner, travel, context, client, headers = env
    saved = runner.run(confirmed(travel, context))
    path = f"/plans/{saved.plan_id}/locks"
    first = str(saved.content.items[0].item_id)

    def lock(version: int, ids: list[str], **kwargs: dict[str, str]) -> object:
        return client.patch(
            path,
            headers=kwargs.get("headers", headers),
            json={"expected_version": version, "locked_item_ids": ids},
        )

    assert lock(1, [], headers={}).status_code == 401  # type: ignore[attr-defined]
    ok = lock(1, [first])
    assert ok.status_code == 200 and ok.json()["version"] == 2  # type: ignore[attr-defined]
    assert [i["locked"] for i in ok.json()["content"]["items"]] == [True, False]  # type: ignore[attr-defined]
    cards = client.get(f"/plans/{saved.plan_id}", headers=headers).json()["cards"]
    assert [card["locked"] for card in cards] == [True, False]
    noop = lock(2, [first])  # 与现状相同：不产生新版本
    assert noop.status_code == 200 and noop.json()["version"] == 2  # type: ignore[attr-defined]

    stale = lock(1, [])
    assert stale.status_code == 409  # type: ignore[attr-defined]
    assert stale.json()["code"] == "conflict"  # type: ignore[attr-defined]
    assert stale.json()["reason"] == "plan_version_changed"  # type: ignore[attr-defined]
    assert "版本" in stale.json()["message"]  # type: ignore[attr-defined]
    assert client.get(f"/plans/{saved.plan_id}", headers=headers).json()["version"] == 2

    unknown = lock(2, [str(uuid4())])
    assert unknown.status_code == 422  # type: ignore[attr-defined]
    assert unknown.json()["code"] == "validation"  # type: ignore[attr-defined]
    assert unknown.json()["reason"] == "lock_invalid"  # type: ignore[attr-defined]

    assert (
        client.patch(
            f"/plans/{uuid4()}/locks",
            headers=headers,
            json={"expected_version": 1, "locked_item_ids": []},
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"expected_version": 0, "locked_item_ids": []}, "expected_version"),
        ({"expected_version": 1, "locked_item_ids": ["not-a-uuid"]}, "locked_item_ids"),
        ({"expected_version": 1}, "locked_item_ids"),
        ({"expected_version": 1, "locked_item_ids": [], "extra": 1}, "extra"),
    ],
)
def test_request_validation_errors_use_the_service_error_shape(
    env: Env, body: dict[str, object], field: str
) -> None:
    runner, travel, context, client, headers = env
    saved = runner.run(confirmed(travel, context))
    response = client.patch(f"/plans/{saved.plan_id}/locks", headers=headers, json=body)
    data = response.json()
    assert response.status_code == 422 and "detail" not in data
    assert data["code"] == "validation" and field in data["message"]
    assert not any(ch.isascii() and ch.isdigit() for ch in data["message"].split("（")[-1])
    bad_path = client.patch("/plans/not-a-uuid/locks", headers=headers, json=body)
    assert bad_path.status_code == 422 and bad_path.json()["code"] == "validation"


# ---- D2/D7：日历 HTTP ----


def unfolded(text: str) -> list[str]:
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    for physical in text.split("\r\n")[:-1]:
        assert len(physical.encode("utf-8")) <= 75, physical
    return text.replace("\r\n ", "").split("\r\n")[:-1]


def utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def test_ics_http_contract_values_uid_sequence_and_escaping(env: Env) -> None:
    runner, travel, context, client, headers = env
    saved = runner.run(confirmed(travel, context))
    name = "金阁寺, 北山;文化\\京\n都" + "长" * 60
    runner.run(stale_evidence(travel, saved.content.items[0].place_evidence_id, name))
    path = f"/plans/{saved.plan_id}/calendar.ics"
    assert client.get(path).status_code == 401
    assert client.get(f"/plans/{uuid4()}/calendar.ics", headers=headers).status_code == 404

    response = client.get(path, headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/calendar; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="trip-v1.ics"'
    assert response.headers["cache-control"] == "no-store"
    lines = unfolded(response.text)
    assert (
        lines[:5]
        == [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Travel Agent//Trip//ZH",
            "CALSCALE:GREGORIAN",
            "BEGIN:VEVENT",
        ]
        and lines[-1] == "END:VCALENDAR"
    )
    events = [
        dict(line.split(":", 1) for line in block.split("\r\n") if ":" in line)
        for block in response.text.replace("\r\n ", "").split("BEGIN:VEVENT\r\n")[1:]
    ]
    assert len(events) == len(saved.content.items) == 2
    for event, item in zip(events, saved.content.items, strict=True):
        assert event["UID"] == f"{item.item_id}@travel-agent"
        assert event["DTSTART"] == utc(item.start) and event["DTEND"] == utc(item.end)
        assert event["DTSTAMP"] == utc(saved.saved_at) and event["SEQUENCE"] == "1"
    # 京都2026-11-03/04 JST落到UTC前一小时段；与服务端保存的具体时刻逐字比较
    assert events[0]["DTSTART"].startswith("202611") and events[0]["DTSTART"].endswith("Z")
    assert events[0]["SUMMARY"] == "金阁寺\\, 北山\\;文化\\\\京\\n都" + "长" * 60
    assert "已过期" in events[0]["DESCRIPTION"]  # 证据过期必须在日历里标注

    again = client.get(path, headers=headers)  # 稳定：同一版本重复下载逐字节相同
    assert again.text == response.text


def test_ics_uid_is_stable_and_sequence_follows_the_plan_version(env: Env) -> None:
    runner, travel, context, client, headers = env
    saved = runner.run(confirmed(travel, context))
    path = f"/plans/{saved.plan_id}/calendar.ics"
    v1 = client.get(path, headers=headers)
    lock = client.patch(
        f"/plans/{saved.plan_id}/locks",
        headers=headers,
        json={"expected_version": 1, "locked_item_ids": [str(saved.content.items[0].item_id)]},
    )
    assert lock.status_code == 200
    v2 = client.get(path, headers=headers)
    assert v2.headers["content-disposition"] == 'attachment; filename="trip-v2.ics"'

    def field(text: str, key: str) -> list[str]:
        return [line.split(":", 1)[1] for line in unfolded(text) if line.startswith(key + ":")]

    assert field(v1.text, "UID") == field(v2.text, "UID")
    assert field(v1.text, "SEQUENCE") == ["1", "1"] and field(v2.text, "SEQUENCE") == ["2", "2"]
    assert "已过期" not in v1.text  # 证据有效时不加噪声


# ---- D4：加锁使待确认草稿失效 ----


def test_locking_invalidates_a_pending_draft_with_a_clear_reason_but_a_noop_lock_does_not(
    env: Env,
) -> None:
    runner, travel, context, _, _ = env
    service = PlanService(travel)

    async def exercise() -> None:
        saved = await confirmed(travel, context)
        pending = await service.stage(context, patch_stage(saved))
        same = await service.locks(
            context.user_id, saved.plan_id, LockInput(expected_version=1, locked_item_ids=())
        )
        assert same.version == 1  # 无变化的锁请求不新建版本，不打断待确认草稿
        await service.locks(
            context.user_id,
            saved.plan_id,
            LockInput(expected_version=1, locked_item_ids=(saved.content.items[0].item_id,)),
        )
        with pytest.raises(ServiceError) as failed:
            await service.confirm(context.user_id, pending.draft_id)
        assert failed.value.status == 409 and failed.value.reason == "plan_version_changed"
        assert "锁定" in str(failed.value) and "重新" in str(failed.value)
        view = await service.get_draft(context.user_id, pending.draft_id)
        assert view["version_changed"] is True
        async with transaction(travel.database) as db:
            plan = await db.get(PlanRow, saved.plan_id)
            assert plan is not None and plan.current_version == 2
        current = await service.locks(  # 现状相同的锁请求取回第2版
            context.user_id,
            saved.plan_id,
            LockInput(expected_version=2, locked_item_ids=(saved.content.items[0].item_id,)),
        )
        again = await service.stage(context, patch_stage(current))
        assert (await service.confirm(context.user_id, again.draft_id)).version == 3

    runner.run(exercise())


# ---- D5：工具与错误细分 ----


def test_items_only_read_exposes_locked_and_patch_errors_tell_missing_from_locked(env: Env) -> None:
    runner, travel, context, _, _ = env
    service = PlanService(travel)

    async def exercise() -> None:
        saved = await confirmed(travel, context)
        locked = await service.locks(
            context.user_id,
            saved.plan_id,
            LockInput(expected_version=1, locked_item_ids=(saved.content.items[1].item_id,)),
        )
        read = await TravelToolExecutor(travel).execute(
            context, "get_saved_plan", {"plan_id": str(saved.plan_id), "items_only": True}
        )
        entries = read.data["item_ids"]
        assert isinstance(entries, list)
        assert [(e["item_id"], e["locked"]) for e in entries] == [
            (str(saved.content.items[0].item_id), False),
            (str(saved.content.items[1].item_id), True),
        ]
        with pytest.raises(ServiceError) as on_locked:
            await service.stage(context, patch_stage(locked))
        assert on_locked.value.status == 422 and on_locked.value.reason == "patch_item_locked"
        assert "锁定" in str(on_locked.value)
        missing = StageInput.model_validate(
            {
                "change": {
                    "kind": "patch",
                    "plan_id": str(saved.plan_id),
                    "patch": {
                        "base_version": 2,
                        "expected_revision": locked.request_revision,
                        "operations": [{"op": "remove", "item_id": str(uuid4())}],
                    },
                }
            }
        )
        with pytest.raises(ServiceError) as on_missing:
            await service.stage(context, missing)
        assert on_missing.value.status == 422 and on_missing.value.reason == "patch_invalid"
        assert "锁定" not in str(on_missing.value)

    runner.run(exercise())


def test_a_failed_first_pass_leaves_no_empty_plan_row(env: Env) -> None:
    """首轮遇硬冲突不落库：不能先commit一个current_version=0、没有草稿的空PlanRow。"""
    runner, travel, context, _, _ = env

    async def exercise() -> None:
        good = await initial_draft(travel, context)
        proposal = good.content.proposal(good.request_revision)
        clash = proposal.items[0].model_copy(update={"end": proposal.items[0].start})
        broken = proposal.model_copy(update={"items": (clash, *proposal.items[1:])})
        args = StageInput.model_validate(
            {"change": {"kind": "initial", "proposal": broken.model_dump(mode="json")}}
        )
        async with transaction(travel.database) as db:  # 清掉上面为取素材暂存的草稿与行程行
            for model in (PlanDraftRow, BusinessOperationRow, PlanRow):
                for row in await db.scalars(
                    select(model).where(model.session_id == context.session_id)
                ):
                    await db.delete(row)
        draft, final = await PlanService(travel)._stage(context, args, None)
        assert draft.validation.status == "conflict" and final is False
        async with transaction(travel.database) as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(PlanRow)
                    .where(PlanRow.session_id == context.session_id)
                )
                == 0
            )

    runner.run(exercise())

"""T4.8：显式授权后的限次酒店覆盖；默认不联网，不保存供应商原始响应。"""

import argparse
import asyncio
import json
import os
import re
from datetime import date, timedelta
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from pydantic import JsonValue, TypeAdapter
from sqlalchemy.exc import SQLAlchemyError

from backend.adapters.external_api import ApiName, ApiUsage
from backend.adapters.rakuten import Rakuten
from backend.domain.external_data import ExternalDataError, GeoPoint
from backend.domain.room_preferences import room_assessment
from backend.domain.travel_request import TravelRequest
from backend.persistence.database import Database, configuration, database_url
from scripts.dev import ROOT

DATES = ("2026-10-17", "2026-11-14")
POINTS = {
    "kyoto": GeoPoint(name="京都", latitude=35.0116, longitude=135.7681),
    "sapporo": GeoPoint(name="札幌", latitude=43.0618, longitude=141.3545),
    "osaka": GeoPoint(name="大阪", latitude=34.6937, longitude=135.5023),
}
PRIVATE = ("住宿：独立房间", "房型：禁烟", "床型：无要求")
DROP = re.compile(
    r"url|application.?id|access.?key|affiliate.?id|token|password|secret|credential|api.?key|referer|origin",
    re.I,
)


def sanitize_payload(
    payload: dict[str, JsonValue], secrets: tuple[str, ...]
) -> dict[str, JsonValue]:
    forbidden = tuple(v for s in secrets if s for v in (s, quote(s, safe="")))

    def clean(value: JsonValue) -> JsonValue:
        if isinstance(value, dict):
            cleaned: dict[str, JsonValue] = {}
            for key, item in value.items():
                if DROP.search(key):
                    continue
                if any(s in key for s in forbidden):
                    raise ValueError("credential found in remaining key; refusing to save")
                cleaned[key] = clean(item)
            return cleaned
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, str) and any(s in value for s in forbidden):
            raise ValueError("credential found in remaining payload; refusing to save")
        return value

    result = clean(payload)
    assert isinstance(result, dict)
    return result


def trip(city: str, day: str, *, nights: int = 1, nonsmoking: bool = True) -> TravelRequest:
    start = date.fromisoformat(day)
    constraints = PRIVATE if nonsmoking else (PRIVATE[0], "房型：无要求", PRIVATE[2])
    return TravelRequest(
        city=city,
        start_date=start,
        end_date=start + timedelta(days=nights),
        adults=1,
        child_ages=(),
        rooms=1,
        revision=1,
        hard_constraints=constraints,
    )


async def replay_two_nights(
    request: TravelRequest, first: dict[str, JsonValue], second: dict[str, JsonValue]
) -> dict[str, int]:
    class ReplayUsage(ApiUsage):
        def __init__(self) -> None:
            self.default_profile = False
            self.run_caps = {"rakuten": 2}
            self.used = {}

        async def consume(self, api: ApiName) -> None:
            self.used[api] = self.used.get(api, 0) + 1

    usage = ReplayUsage()

    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=first if usage.used["rakuten"] == 1 else second)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        offers = await Rakuten("test", "test", "", "", http, usage).search(
            request, GeoPoint(name=request.city or "", latitude=0, longitude=0), limit=5
        )
    complete = sum(o.included_total is not None for o in offers)
    return {
        "shown": len(offers),
        "complete_totals": complete,
        "unknown_totals": len(offers) - complete,
        "replay_requests": usage.used["rakuten"],
    }


async def exercise() -> list[dict[str, object]]:
    database = Database(database_url(configuration()))
    environment = dict(os.environ)
    environment["TRAVEL_PROFILE"] = "default"
    environment["RAKUTEN_DAILY_CAP"] = str(
        min(int(environment.get("RAKUTEN_DAILY_CAP") or 150), 30)
    )
    usage = ApiUsage(database, environment, run_limits=False)
    app, access = environment.get("RAKUTEN_APP_ID", ""), environment.get("RAKUTEN_ACCESS_KEY", "")
    if not app or not access:
        await database.close()
        raise ValueError("Rakuten credentials unavailable")
    secrets = (app, access, environment.get("RAKUTEN_AFFILIATE_ID", ""))
    captured: list[dict[str, JsonValue]] = []
    page = 1
    results: list[dict[str, object]] = []
    firsts: dict[tuple[str, str], dict[str, JsonValue]] = {}
    ids: dict[tuple[str, str], tuple[int, ...]] = {}
    counts: dict[tuple[str, str], int] = {}

    async def request_hook(request: httpx.Request) -> None:
        request.url = request.url.copy_set_param("page", page)

    async def capture(response: httpx.Response) -> None:
        await response.aread()
        if response.is_success:
            payload = TypeAdapter(dict[str, JsonValue]).validate_python(response.json())
            captured.append(sanitize_payload(payload, secrets))

    try:
        async with httpx.AsyncClient(
            event_hooks={"request": [request_hook], "response": [capture]}
        ) as http:
            rakuten = Rakuten(
                app,
                access,
                environment.get("RAKUTEN_AFFILIATE_ID", ""),
                environment.get("RAKUTEN_REFERER", ""),
                http,
                usage,
            )

            async def query(
                city: str,
                day: str,
                label: str,
                *,
                by_plan: bool = False,
                nonsmoking: bool = True,
                hotel_ids: tuple[int, ...] = (),
                selected_page: int = 1,
            ) -> dict[str, JsonValue]:
                nonlocal page
                if usage.used.get("rakuten", 0) >= 21:
                    raise ValueError("probe request cap reached")
                page = selected_page
                captured.clear()
                request = trip(POINTS[city].name, day, nonsmoking=nonsmoking)
                items, count = await rakuten.query(
                    request, date.fromisoformat(day), POINTS[city], hotel_ids, by_plan=by_plan
                )
                payload = captured[0] if captured else {"hotels": []}
                filename = f"rakuten_{city}_{label}_{day}.json"
                (ROOT / "tests" / "fixtures" / filename).write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                selected = Rakuten.lowest_per_hotel(items, request)[:5]
                per_hotel: dict[int, int] = {}
                for item in items:
                    per_hotel[item.hotel.hotelNo] = per_hotel.get(item.hotel.hotelNo, 0) + 1
                result: dict[str, object] = {
                    "city": city,
                    "day": day,
                    "probe": label,
                    "page": page,
                    "record_count": count,
                    "returned_hotels": len(per_hotel),
                    "plans": len(items),
                    "max_plans_per_hotel": max(per_hotel.values(), default=0),
                    "below_price_floor": sum(Rakuten.price_unreliable(i, request) for i in items),
                    "dorm_capsule": sum(
                        room_assessment(i.room.roomName, request).room_preference_mismatch
                        for i in items
                    ),
                    "restricted": sum(
                        room_assessment(i.room.roomName, request).qualification_unknown
                        for i in items
                    ),
                    "nonsmoking_name": sum("禁煙" in i.room.roomName for i in items),
                    "shown": len(selected),
                    "fixture": filename,
                }
                if label == "coverage":
                    firsts[city, day] = payload
                    ids[city, day] = tuple(i.hotel.hotelNo for i in selected)
                    counts[city, day] = count or 0
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                # 明确节流，无重试；下一次仍先由ApiUsage原子预占。
                await asyncio.sleep(1.2)
                return payload

            for city in POINTS:
                for day in DATES:
                    await query(city, day, "coverage")
            for city in POINTS:
                await query(city, DATES[0], "pattern1", by_plan=True)
                await query(city, DATES[0], "without_kinen", nonsmoking=False)
            for city in POINTS:
                for day in DATES:
                    hotel_ids = ids[city, day]
                    if not hotel_ids:
                        results.append(
                            {"city": city, "day": day, "multi_night": "no_eligible_hotel"}
                        )
                        continue
                    second_day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
                    second = await query(city, second_day, "second_night", hotel_ids=hotel_ids)
                    replay = await replay_two_nights(
                        trip(POINTS[city].name, day, nights=2), firsts[city, day], second
                    )
                    results.append({"city": city, "day": day, "multi_night": replay})
                    print(json.dumps(results[-1], ensure_ascii=False), flush=True)
            for city in POINTS:
                if counts[city, DATES[0]] > 30:
                    await query(city, DATES[0], "page2", selected_page=2)
    finally:
        (ROOT / ".cache").mkdir(exist_ok=True)
        (ROOT / ".cache" / "hotel-coverage-summary.json").write_text(
            json.dumps(
                {"requests": usage.used.get("rakuten", 0), "results": results},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        await database.close()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="授权后逐批探针，UTC当日累计最多30次")
    args = parser.parse_args()
    if not args.live:
        print("offline-plan: coverage=6, contrasts=6, second_nights<=6, page2<=3, real_calls=0")
        return 0
    load_dotenv(ROOT / ".env", encoding="utf-8")
    try:
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(exercise())
        return 0
    except (SQLAlchemyError, ExternalDataError, ValueError, OSError) as error:
        print(json.dumps({"probe_stopped": type(error).__name__, "no_retry": True}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

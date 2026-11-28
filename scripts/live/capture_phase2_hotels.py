"""乐天一次性酒店评测采样。只在本机保存筛过的报价字段。"""

import argparse
import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError
from sqlalchemy import text

from backend.adapters.external_api import ApiUsage
from backend.adapters.rakuten import Candidate, Rakuten
from backend.domain.external_data import ExternalDataError, GeoPoint
from backend.domain.travel_request import TravelRequest, tokyo_today
from backend.persistence.database import Database, configuration, database_url
from backend.providers.claude_agent.live import phase2_checkout_root
from data.eval_world.generate import write_world
from data.eval_world.world import Demand, Hotel, Station, World, load_world
from scripts.dev import ROOT

MAX_ATTEMPTS = 40
PRIVATE_DIRECTORY = Path(".cache/phase2/rakuten-private-v1")
DEMANDS: tuple[Demand, ...] = ("weekday", "weekend", "event")
PARTIES = (1, 2)


class ObservedRate(BaseModel):
    hotel_id: int
    name: str
    latitude: float
    longitude: float
    rating: float
    reviews: int
    breakfast: bool
    price: int


type Quotes = dict[tuple[int, bool], ObservedRate]
type StayDates = Mapping[Demand, date]


def eligible_quotes(items: Sequence[Candidate], trip: TravelRequest) -> Quotes:
    assert trip.start_date
    quotes: Quotes = {}
    for item in items:
        hotel, flag = item.hotel, item.room.withBreakfastFlag
        price = Rakuten.price(item, trip, trip.start_date)
        if (
            price is None
            or price != price.to_integral_value()
            or Rakuten.price_unreliable(item, trip)
            or hotel.latitude is None
            or hotel.longitude is None
            or hotel.reviewAverage is None
            or not 0 <= hotel.reviewAverage <= 5
            or hotel.reviewCount is None
            or flag not in (0, 1)
        ):
            continue
        key = hotel.hotelNo, bool(flag)
        if key not in quotes or price < quotes[key].price:
            quotes[key] = ObservedRate(
                hotel_id=hotel.hotelNo,
                name=hotel.hotelName,
                latitude=hotel.latitude,
                longitude=hotel.longitude,
                rating=hotel.reviewAverage,
                reviews=hotel.reviewCount,
                breakfast=bool(flag),
                price=int(price),
            )
    return quotes


def select_hotels(station: Station, groups: Mapping[tuple[Demand, int], Quotes]) -> list[Hotel]:
    keys = [(demand, adults) for demand in DEMANDS for adults in PARTIES]
    best: dict[tuple[Demand, int], dict[int, ObservedRate]] = {}
    for group in keys:
        rates: dict[int, ObservedRate] = {}
        for quote in groups.get(group, {}).values():
            previous = rates.get(quote.hotel_id)
            if previous is None or (quote.price, quote.breakfast) < (
                previous.price,
                previous.breakfast,
            ):
                rates[quote.hotel_id] = quote
        best[group] = rates
    remaining = {hotel_id for rates in best.values() for hotel_id in rates}
    covers = dict.fromkeys(keys, 0)
    hotels: list[Hotel] = []
    while remaining and len(hotels) < 20:

        def coverage(hotel_id: int) -> tuple[list[int], int]:
            return sorted(covers[group] + (hotel_id in best[group]) for group in keys), -hotel_id

        hotel_id = max(remaining, key=coverage)
        remaining.remove(hotel_id)
        selected = {group: rates[hotel_id] for group, rates in best.items() if hotel_id in rates}
        sample = next(iter(selected.values()))
        by_demand = {
            demand: (selected.get((demand, 1)), selected.get((demand, 2))) for demand in DEMANDS
        }
        for group in selected:
            covers[group] += 1
        hotels.append(
            Hotel(
                hotel_id=f"rakuten:{sample.hotel_id}",
                city=station.city,
                name=sample.name,
                latitude=sample.latitude,
                longitude=sample.longitude,
                rating=sample.rating,
                reviews=sample.reviews,
                breakfast=sample.breakfast,
                prices_jpy={
                    demand: (one.price if one else None, two.price if two else None)
                    for demand, (one, two) in by_demand.items()
                },
                breakfast_by_demand={
                    demand: (one.breakfast if one else None, two.breakfast if two else None)
                    for demand, (one, two) in by_demand.items()
                },
            )
        )
    return hotels


def read_groups(path: Path) -> dict[tuple[Demand, int], Quotes]:
    groups: dict[tuple[Demand, int], Quotes] = {}
    for demand in DEMANDS:
        for adults in PARTIES:
            rows = json.loads((path / f"{demand}-{adults}.json").read_text(encoding="utf-8"))
            quotes = [ObservedRate.model_validate(record) for record in rows]
            groups[demand, adults] = {(rate.hotel_id, rate.breakfast): rate for rate in quotes}
    return groups


def assemble(target: Path) -> int:
    stations = load_world()[0].stations
    try:
        summary = json.loads((target / "summary.json").read_text(encoding="utf-8"))
        hotels = {
            station.city: select_hotels(station, read_groups(target / station.city))
            for station in stations
        }
    except (OSError, ValueError):
        print("本机录制记录缺失或格式不符。")
        return 2
    try:
        world = World(
            source="rakuten",
            stations=stations,
            hotels=tuple(hotel for city_hotels in hotels.values() for hotel in city_hotels),
        )
    except ValidationError:
        print("已录制的报价覆盖未满足六城快照约束。")
        return 2
    write_world(world, target, live_calls=summary["http_attempts"])
    load_world(target, source="rakuten")
    coverage = {
        city: {
            f"{demand}-{party + 1}": sum(
                hotel.prices_jpy[demand][party] is not None for hotel in city_hotels
            )
            for demand in DEMANDS
            for party in range(2)
        }
        for city, city_hotels in hotels.items()
    }
    report = {
        "http_attempts": summary["http_attempts"],
        "hotels_by_city": {city: len(city_hotels) for city, city_hotels in hotels.items()},
        "coverage_by_stay": coverage,
    }
    result = json.dumps(report, ensure_ascii=False, indent=2)
    (target / "world-validation.json").write_text(result + "\n", encoding="utf-8")
    print(result)
    return 0


async def capture_city(provider: Rakuten, station: Station, dates: StayDates, output: Path) -> None:
    point = GeoPoint(name=station.city, latitude=station.latitude, longitude=station.longitude)
    for demand, day in dates.items():
        for adults in PARTIES:
            trip = TravelRequest(
                city=station.city,
                start_date=day,
                end_date=day + timedelta(days=1),
                adults=adults,
                child_ages=(),
                rooms=1,
            )
            items = await provider.nightly(trip, day, point)
            quotes = eligible_quotes(items, trip)
            (output / f"{demand}-{adults}.json").write_text(
                json.dumps([quote.model_dump() for quote in quotes.values()], ensure_ascii=False),
                encoding="utf-8",
            )


async def capture(dates: StayDates) -> int:
    load_dotenv(ROOT / ".env")
    required = ("RAKUTEN_APP_ID", "RAKUTEN_ACCESS_KEY")
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        print("缺少配置 " + ", ".join(missing))
        return 2
    target = phase2_checkout_root(ROOT) / PRIVATE_DIRECTORY
    if target.exists():
        print("一次性采样目录已存在，使用已有记录。")
        return 2
    dsn = database_url(configuration())
    if dsn.host not in {"127.0.0.1", "localhost"}:
        print("本机采样使用本地 PostgreSQL 配额账本。")
        return 2
    database = Database(dsn)
    try:
        usage = ApiUsage(database, os.environ)
        async with database.sessions() as session:
            used = await session.scalar(
                text("SELECT calls FROM external_api_usage WHERE day=:day AND api='rakuten'"),
                {"day": datetime.now(UTC).date()},
            )
        left = usage.daily["rakuten"] - (used or 0)
        planned = len(DEMANDS) * len(PARTIES) * len(load_world()[0].stations)
        if left < planned:
            print(f"今日乐天配额剩余 {left} 次，完整采样需要 {planned} 次。")
            return 2
        print(f"本地乐天配额剩余 {left} 次，计划 {planned} 次查询。", flush=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.mkdir(mode=0o700)
        except FileExistsError:
            print("一次性采样目录已存在，使用已有记录。")
            return 2
        usage.run_caps["rakuten"] = MAX_ATTEMPTS
        usage.rakuten_interval = max(1.1, usage.rakuten_interval)
        return await record(dates, usage, target)
    finally:
        await database.close()


async def record(dates: StayDates, usage: ApiUsage, target: Path) -> int:
    world, _ = load_world()
    recorded: list[str] = []
    error_code: str | None = None
    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as http:
            provider = Rakuten(
                os.environ["RAKUTEN_APP_ID"],
                os.environ["RAKUTEN_ACCESS_KEY"],
                "",
                os.environ.get("RAKUTEN_REFERER", ""),
                http,
                usage,
            )
            for station in world.stations:
                folder = target / station.city
                folder.mkdir()
                await capture_city(provider, station, dates, folder)
                recorded.append(station.city)
    except ExternalDataError as error:
        error_code = f"{error.info.kind or 'invalid_response'}:{error.info.status or '-'}"
    attempts = usage.used.get("rakuten", 0)
    report = json.dumps(
        {
            "dates": {demand: day.isoformat() for demand, day in dates.items()},
            "http_attempts": attempts,
            "recorded_cities": recorded,
            "error": error_code,
        },
        ensure_ascii=False,
        indent=2,
    )
    (target / "summary.json").write_text(report + "\n", encoding="utf-8")
    print(report)
    return 1 if error_code else assemble(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--assemble", action="store_true")
    for demand in DEMANDS:
        parser.add_argument(f"--{demand}", type=date.fromisoformat)
    args = parser.parse_args()
    if args.assemble:
        return assemble(phase2_checkout_root(ROOT) / PRIVATE_DIRECTORY)
    dates: StayDates = {"weekday": args.weekday, "weekend": args.weekend, "event": args.event}
    if (
        None in dates.values()
        or len(set(dates.values())) != 3
        or min(dates.values()) < tokyo_today()
    ):
        parser.error("请输入三个不同的有效入住日期")
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(capture(dates))


if __name__ == "__main__":
    raise SystemExit(main())

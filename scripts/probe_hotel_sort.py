"""授权后的两次排序探针；使用现有计数/节流，不保存原始响应、密钥或酒店标识。"""

import argparse
import asyncio
import json
import os
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
from dotenv import load_dotenv

from backend.adapters.external_api import ApiUsage
from backend.adapters.rakuten import Rakuten
from backend.domain.external_data import ExternalDataError, GeoPoint
from backend.domain.travel_request import TravelRequest
from backend.persistence.database import Database, configuration, database_url
from scripts.dev import ROOT

KYOTO = GeoPoint(name="京都", latitude=35.0116, longitude=135.7681)


def trip(city: str, day: str, *, nights: int = 1) -> TravelRequest:
    start = date.fromisoformat(day)
    return TravelRequest(
        city=city,
        start_date=start,
        end_date=start + timedelta(days=nights),
        adults=1,
        child_ages=(),
        rooms=1,
        revision=1,
        hard_constraints=("住宿：独立房间", "房型：禁烟", "床型：无要求"),
    )


async def exercise() -> int:
    load_dotenv(ROOT / ".env")
    database = Database(database_url(configuration()))
    usage = ApiUsage(database, os.environ)
    usage.run_caps["rakuten"] = 2  # 包括HTTP失败重试，总计最多2次；不绕过每日额度。
    request = trip("京都", "2026-11-14").model_copy(update={"adults": 2})
    report: dict[str, object] = {
        "date": datetime.now(UTC).isoformat(),
        "stay": "2026-11-14/15",
        "adults": 2,
        "rooms": 1,
        "search_pattern": 0,
        "max_http_attempts": 2,
        "source": "https://webservice.rakuten.co.jp/documentation/vacant-hotel-search",
    }
    results: list[dict[str, object]] = []
    try:
        app, access = os.environ.get("RAKUTEN_APP_ID", ""), os.environ.get("RAKUTEN_ACCESS_KEY", "")
        if not app or not access:
            print("乐天凭据未配置；未发请求。")
            return 2
        async with httpx.AsyncClient() as http:
            provider = Rakuten(
                app,
                access,
                os.environ.get("RAKUTEN_AFFILIATE_ID", ""),
                os.environ.get("RAKUTEN_REFERER", ""),
                http,
                usage,
            )
            assert request.start_date
            for sort in ("standard", "+roomCharge"):
                if usage.used.get("rakuten", 0) >= 2:
                    break
                items, count = await provider.query(request, request.start_date, KYOTO, sort=sort)
                room_prices: dict[int, Decimal] = {}
                raw_prices: dict[int, Decimal] = {}
                for item in items:
                    price = Rakuten.price(item, request, request.start_date)
                    if price is None or item.charge is None:
                        continue
                    no = item.hotel.hotelNo
                    room_prices[no] = min(room_prices.get(no, price), price)
                    raw_prices[no] = min(
                        raw_prices.get(no, item.charge.rakutenCharge), item.charge.rakutenCharge
                    )
                normalized, raw = list(room_prices.values()), list(raw_prices.values())
                results.append(
                    {
                        "sort": sort,
                        "record_count": count,
                        "returned_hotels": len(room_prices),
                        "returned_room_plans": len(items),
                        "charge_flags": dict(
                            Counter(i.charge.chargeFlag for i in items if i.charge)
                        ),
                        "room_prices": [str(p) for p in normalized],
                        "room_price_ascending": normalized == sorted(normalized),
                        "raw_price_ascending": raw == sorted(raw),
                        "qualified": len(provider.lowest_per_hotel(items, request)),
                    }
                )
    except ExternalDataError as error:
        report["error"] = {"kind": error.info.kind, "http_status": error.info.status}
    finally:
        await database.close()
    report["queries"], report["http_attempts"] = results, usage.used.get("rakuten", 0)
    report["unit_basis"] = (
        "VERIFIED官方：chargeFlag=0每人，1每间；仅当晚价格，price()乘实际成人/房数。"
    )
    report["sorting_basis"] = (
        "官方定义价格升序；上述顺序只验证本次样本，不推断所有日期/混合单位的保证。"
    )
    target = ROOT / "docs/evidence/t4-rakuten-sort-2026-10-13.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if len(results) == 2 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    if not parser.parse_args().live:
        return 2
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(exercise())


if __name__ == "__main__":
    raise SystemExit(main())

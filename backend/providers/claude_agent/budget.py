"""SDK 联网前持久预占，完整 usage 后结算；未知费用保留全部预占。"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from backend.providers.claude_agent.ledger import Ledger
from backend.providers.claude_agent.limits import Currency, ProbeError, read_budget
from backend.providers.claude_agent.profile import current
from backend.trace_log import trace

GRANT = "2026-10-03-travel-autonomous"
# 用户新授权只限制每日15CNY；None表示没有累计上限，不用伪造大数。
DAILY_CNY_AUTHORIZATION = Decimal("15.00")
# 用户明确仅今日暂停日限；原账本和其他日期的限制不变。
UNCAPPED_CNY_DAY = "2026-10-04"
LIMITS: dict[Currency, tuple[Decimal | None, int | None]] = {
    "CNY": (None, None),
    "USD": (Decimal(0), 0),
}


def check_authorization(currency: Currency) -> None:
    amount, count = LIMITS[currency]
    if (amount is not None and amount <= 0) or (count is not None and count <= 0):
        raise ProbeError("blocked", "美元累计金额和次数授权均为0；日预算不能授予调用权限")


@dataclass(frozen=True)
class Entry:
    """每个请求一条预占、至多一条结算；不保存正文或密钥。"""

    grant: str
    request_id: str
    kind: str
    day: str
    charge: str
    currency: Currency


class Budget:
    """调用方须持有进程锁，守卫顺序服务请求，避免并发检查余额。"""

    def __init__(
        self, path: Path, legacy: Path, daily: Decimal, currency: Currency = "CNY"
    ) -> None:
        self.path, self.legacy, self.daily = path, legacy, daily
        self.currency = currency

    def check_authorization(self) -> None:
        check_authorization(self.currency)

    def daily_limit(self, now: datetime) -> Decimal | None:
        """None仅表示获准日期无日限；零配置仍在预占前拒绝。"""
        if self.currency == "CNY":
            if not current().daily_cny_cap:  # HUMAN档：以供应商账户余额为准，不设每日上限
                return None
            if now.astimezone(UTC).date().isoformat() == UNCAPPED_CNY_DAY:
                return None
            return min(self.daily, DAILY_CNY_AUTHORIZATION)
        return self.daily

    def check_minimum_requests(self, minimum: int) -> None:
        """只做必要条件预检；实际费用/辅助调用仍逐HTTP预占，不承诺整集足够。"""
        if type(minimum) is not int or minimum < 1:
            raise ProbeError("validation", "计划请求数必须为正整数")
        self.check_authorization()
        used, _ = self.totals()
        limit = LIMITS[self.currency][1]
        if limit is not None and used + minimum > limit:
            raise ProbeError("blocked", "即使每案例只请求一次，累计授权也不足完整评测")

    def entries(self) -> list[Entry]:
        if not self.path.exists():
            return []
        entries: list[Entry] = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                raw: object = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError
                # 旧人民币账本只在读取边界归一化，绝不重写、重置或解释成美元。
                if set(raw) == {"grant", "request_id", "kind", "day", "charge_cny"}:
                    raw = {**raw, "charge": raw["charge_cny"], "currency": "CNY"}
                    del raw["charge_cny"]
                if set(raw) != set(Entry.__dataclass_fields__):
                    raise ValueError
                if not all(isinstance(v, str) for v in raw.values()):
                    raise ValueError
                entry = Entry(**raw)
                if (
                    entry.grant != GRANT
                    or entry.kind not in {"attempt", "settled"}
                    or entry.currency != self.currency
                ):
                    raise ValueError
                if not entry.request_id or read_budget(entry.charge) < 0:
                    raise ValueError
                datetime.strptime(entry.day, "%Y-%m-%d")
                entries.append(entry)
            _charges(entries)
        except (ValueError, TypeError, ProbeError, UnicodeError):
            raise ProbeError("blocked", "SDK 费用账本损坏；禁止清空重跑") from None
        return entries

    def append(self, entry: Entry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = asdict(entry)
        if entry.currency == "CNY":
            raw["charge_cny"] = raw.pop("charge")
            del raw["currency"]
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(raw) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def reserve(self, amount: Decimal, now: datetime, run: object = None) -> str:
        self.check_authorization()
        entries = self.entries()
        charges = _charges(entries)
        day = now.astimezone(UTC).date().isoformat()
        total = sum((value for _, value in charges.values()), Decimal(0))
        daily = sum((v for d, v in charges.values() if d == day), Decimal(0))
        daily += sum(
            (
                Decimal(e.charge)
                for e in Ledger(self.legacy).entries()
                if e.day == day and e.currency == self.currency
            ),
            Decimal(0),
        )
        capped = self.currency != "CNY" or current().daily_cny_cap
        daily_limit = self.daily_limit(now) if self.daily.is_finite() else None
        numbers = {  # 仅数字/日期，供TRACE判断是哪个额度触发
            "day": day,
            "daily_spent": str(daily),
            "request_amount": str(amount),
            "daily_limit": None if daily_limit is None else str(daily_limit),
            "daily_cap": capped,
            "entries_today": sum(1 for d, _ in charges.values() if d == day),
            "unsettled_today": sum(
                1
                for rid, (d, _) in charges.items()
                if d == day
                and not any(e.request_id == rid and e.kind == "settled" for e in entries)
            ),
            "currency": self.currency,
        }
        if (
            not amount.is_finite()
            or amount <= 0
            or (capped and (not self.daily.is_finite() or self.daily <= 0))
        ):
            trace("budget_block", run, cause="invalid", **numbers)
            raise ProbeError("blocked", "日预算非法或已禁用")
        total_limit, request_limit = LIMITS[self.currency]
        if (request_limit is not None and len(charges) >= request_limit) or (
            total_limit is not None and total + amount > total_limit
        ):
            trace("budget_block", run, cause="cumulative", **numbers)
            raise ProbeError("blocked", "已达用户累计调用授权上限")
        if daily_limit is not None and daily + amount > daily_limit:
            trace("budget_block", run, cause="daily", **numbers)
            raise ProbeError("blocked", "今日原币种余额不足")
        request_id = str(uuid4())
        # 不变量：先 fsync 才联网；没有结算记录的尝试始终按全部预占计费。
        self.append(Entry(GRANT, request_id, "attempt", day, str(amount), self.currency))
        trace(
            "budget_reserved",
            run,
            **{**numbers, "daily_spent": str(daily + amount)},
        )
        return request_id

    def settle(self, request_id: str, amount: Decimal) -> None:
        entries = self.entries()
        attempt = next((e for e in entries if e.request_id == request_id), None)
        if attempt is None:
            raise ProbeError("blocked", "结算必须对应已预占的请求")
        candidate = Entry(GRANT, request_id, "settled", attempt.day, str(amount), self.currency)
        _charges([*entries, candidate])
        self.append(candidate)

    def totals(self) -> tuple[int, Decimal]:
        charges = _charges(self.entries())
        return len(charges), sum((v for _, v in charges.values()), Decimal(0))


def _charges(entries: list[Entry]) -> dict[str, tuple[str, Decimal]]:
    charges: dict[str, tuple[str, Decimal]] = {}
    settled: set[str] = set()
    for entry in entries:
        amount = read_budget(entry.charge)
        previous = charges.get(entry.request_id)
        if entry.kind == "attempt":
            if previous is not None or amount <= 0:
                raise ProbeError("blocked", "重复或非法预占")
        elif (
            previous is None
            or entry.request_id in settled
            or entry.day != previous[0]
            or amount > previous[1]
        ):
            raise ProbeError("blocked", "无效或重复结算")
        else:
            settled.add(entry.request_id)
        charges[entry.request_id] = entry.day, amount
    return charges

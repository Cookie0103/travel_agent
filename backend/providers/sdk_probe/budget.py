"""SDK 联网前持久预占，完整 usage 后结算；未知费用保留全部预占。"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from backend.providers.probe.ledger import Ledger
from backend.providers.probe.settings import ProbeError, read_budget

GRANT = "2026-10-03-travel-autonomous"
TOTAL_CNY = Decimal("5.00")
TOTAL_REQUESTS = 100


@dataclass(frozen=True)
class Entry:
    """每个请求一条预占、至多一条结算；不保存正文或密钥。"""

    grant: str
    request_id: str
    kind: str
    day: str
    charge_cny: str


class Budget:
    """调用方须持有进程锁，守卫顺序服务请求，避免并发检查余额。"""

    def __init__(self, path: Path, legacy: Path, daily: Decimal) -> None:
        self.path, self.legacy, self.daily = path, legacy, daily

    def entries(self) -> list[Entry]:
        if not self.path.exists():
            return []
        entries: list[Entry] = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                raw: object = json.loads(line)
                if not isinstance(raw, dict) or set(raw) != set(Entry.__dataclass_fields__):
                    raise ValueError
                if not all(isinstance(v, str) for v in raw.values()):
                    raise ValueError
                entry = Entry(**raw)
                if entry.grant != GRANT or entry.kind not in {"attempt", "settled"}:
                    raise ValueError
                if not entry.request_id or read_budget(entry.charge_cny) < 0:
                    raise ValueError
                datetime.strptime(entry.day, "%Y-%m-%d")
                entries.append(entry)
            _charges(entries)
        except (ValueError, TypeError, ProbeError, UnicodeError):
            raise ProbeError("blocked", "SDK 费用账本损坏；禁止清空重跑") from None
        return entries

    def append(self, entry: Entry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(asdict(entry)) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def reserve(self, amount: Decimal, now: datetime) -> str:
        entries = self.entries()
        charges = _charges(entries)
        day = now.astimezone(UTC).date().isoformat()
        total = sum((value for _, value in charges.values()), Decimal(0))
        daily = sum((v for d, v in charges.values() if d == day), Decimal(0))
        daily += sum(
            (
                Decimal(e.charge)
                for e in Ledger(self.legacy).entries()
                if e.day == day and e.currency == "CNY"
            ),
            Decimal(0),
        )
        if not amount.is_finite() or amount <= 0 or not self.daily.is_finite() or self.daily <= 0:
            raise ProbeError("blocked", "人民币预算非法或已禁用")
        if len(charges) >= TOTAL_REQUESTS or total + amount > TOTAL_CNY:
            raise ProbeError("blocked", "已达用户累计调用授权上限")
        if daily + amount > self.daily:
            raise ProbeError("blocked", "今日人民币余额不足")
        request_id = str(uuid4())
        # 不变量：先 fsync 才联网；没有结算记录的尝试始终按全部预占计费。
        self.append(Entry(GRANT, request_id, "attempt", day, str(amount)))
        return request_id

    def settle(self, request_id: str, amount: Decimal) -> None:
        entries = self.entries()
        attempt = next((e for e in entries if e.request_id == request_id), None)
        if attempt is None:
            raise ProbeError("blocked", "结算必须对应已预占的请求")
        candidate = Entry(GRANT, request_id, "settled", attempt.day, str(amount))
        _charges([*entries, candidate])
        self.append(candidate)

    def totals(self) -> tuple[int, Decimal]:
        charges = _charges(self.entries())
        return len(charges), sum((v for _, v in charges.values()), Decimal(0))


def _charges(entries: list[Entry]) -> dict[str, tuple[str, Decimal]]:
    charges: dict[str, tuple[str, Decimal]] = {}
    settled: set[str] = set()
    for entry in entries:
        amount = read_budget(entry.charge_cny)
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

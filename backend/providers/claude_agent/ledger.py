"""实测前持久计次和占用保守费用；失败及中断不退回次数或费用。"""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from backend.providers.claude_agent.limits import Currency, ProbeError, read_budget


@dataclass(frozen=True)
class Entry:
    """账本只保存计数和金额，不保存请求正文或认证信息。"""

    kind: str
    day: str
    currency: Currency
    charge: str = "0"


@contextmanager
def exclusive(path: Path) -> Iterator[None]:
    """整次流程互斥；异常终止遗留锁时拒绝盲目恢复。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write("M0.2 running\n")
    except FileExistsError:
        raise ProbeError("blocked", "探针正在运行或上次中断尚待核对账本") from None
    try:
        yield
    finally:
        path.unlink()


class Ledger:
    """调用方须持有流程锁；日额度按 UTC，批次次数不按日重置。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def entries(self) -> list[Entry]:
        if not self.path.exists():
            return []
        entries: list[Entry] = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                raw: object = json.loads(line)
                if not isinstance(raw, dict) or set(raw) != {"kind", "day", "currency", "charge"}:
                    raise ValueError
                if raw["kind"] not in {"flow", "attempt", "success"}:
                    raise ValueError
                if raw["currency"] not in {"CNY", "USD"}:
                    raise ValueError
                if not isinstance(raw["day"], str) or not isinstance(raw["charge"], str):
                    raise ValueError
                datetime.strptime(raw["day"], "%Y-%m-%d")
                read_budget(raw["charge"])
                entries.append(Entry(raw["kind"], raw["day"], raw["currency"], raw["charge"]))
        except (ValueError, TypeError, ProbeError):
            raise ProbeError("blocked", "账本损坏，禁止清空后自动重跑") from None
        return entries

    def append(self, entry: Entry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(asdict(entry)) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def start_flow(self, now: datetime) -> None:
        entries = self.entries()
        if any(entry.kind == "success" for entry in entries):
            raise ProbeError("blocked", "已成功实测，避免重复花费")
        if sum(entry.kind == "flow" for entry in entries) >= 2:
            raise ProbeError("blocked", "本批已到两次流程上限")
        self.append(Entry("flow", now.astimezone(UTC).date().isoformat(), "CNY"))

    def charge(self, currency: Currency, amount: Decimal, limit: Decimal, now: datetime) -> None:
        entries = self.entries()
        day = now.astimezone(UTC).date().isoformat()
        if sum(entry.kind == "attempt" for entry in entries) >= 4:
            raise ProbeError("blocked", "本批已到四次请求上限")
        spent = sum(
            (Decimal(e.charge) for e in entries if e.day == day and e.currency == currency),
            Decimal("0"),
        )
        if not amount.is_finite() or amount <= 0 or not limit.is_finite() or spent + amount > limit:
            raise ProbeError("blocked", "本币种预算不足")
        # 不变量：先落盘再请求；超时、进程中断也不会把本次视为零消耗。
        self.append(Entry("attempt", day, currency, str(amount)))

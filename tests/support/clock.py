"""只在离线测试及其子进程固定旅行日历，墙钟和缓存有效期照常走时。"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time
from unittest.mock import patch

from backend.domain import travel_request
from backend.domain.opening_hours import TOKYO

FIXTURE_TODAY = date(2026, 10, 10)
FIXTURE_TODAY_ENV = "TRAVEL_TEST_TODAY"


@contextmanager
def fixture_travel_calendar() -> Iterator[None]:
    value = os.environ.get(FIXTURE_TODAY_ENV)
    if value is None:
        yield
        return
    fixed_now = datetime.combine(date.fromisoformat(value), time.min, TOKYO)
    # TravelService 的默认参数已绑定 tokyo_today，要替换函数内部读时钟的对象。
    with patch.object(travel_request, "datetime", wraps=datetime) as clock:
        clock.now.return_value = fixed_now
        yield

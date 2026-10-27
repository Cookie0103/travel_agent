"""E6：/demo/login 按客户端IP和全局的进程内滑动窗口限流，超限429 + Retry-After。"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import URL

from backend.api.app import create_app
from backend.services.sessions import SessionService
from tests.runner import SELECTOR_OPTIONS

pytestmark = pytest.mark.integration


class Clock:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def limited(postgres_url: URL) -> Iterator[tuple[SessionService, Clock]]:
    clock = Clock()
    yield (
        SessionService(
            postgres_url,
            demo_enabled=True,
            login_per_ip=2,
            login_global=3,
            login_seconds=60,
            clock=clock,
        ),
        clock,
    )


def post(app: FastAPI, ip: str) -> Response:
    with TestClient(
        app,
        client=(ip, 50000),
        backend_options=SELECTOR_OPTIONS,
    ) as client:
        return client.post("/demo/login", json={"display_name": "旅行者"})


def test_per_ip_then_global_limit_with_retry_after_and_recovery(
    limited: tuple[SessionService, Clock],
) -> None:
    service, clock = limited
    app = create_app(service)
    assert [post(app, "10.0.0.1").status_code for _ in range(2)] == [201, 201]
    blocked = post(app, "10.0.0.1")
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limited"
    assert 0 < int(blocked.headers["Retry-After"]) <= 60
    assert post(app, "10.0.0.2").status_code == 201  # 另一个IP不受影响
    # 全局上限(3)已满：新IP也被拒，限流不能靠换IP绕过。
    assert post(app, "10.0.0.3").status_code == 429
    clock.now += 61
    assert post(app, "10.0.0.1").status_code == 201


def test_disabled_demo_is_not_counted_and_defaults_are_generous(postgres_url: URL) -> None:
    disabled = SessionService(postgres_url, demo_enabled=False, login_per_ip=1)
    app = create_app(disabled)
    assert [post(app, "10.0.0.9").status_code for _ in range(3)] == [403, 403, 403]
    default = SessionService(postgres_url, demo_enabled=True)
    assert default.login_ip.limit >= 20 and default.login_all.limit >= 100


def test_environment_configures_and_caps_limits() -> None:
    service = SessionService.from_environment(
        {
            "POSTGRES_PASSWORD": "unused",  # 只为通过配置校验；CI 没有 .env
            "DEMO_MODE": "true",
            "DEMO_LOGIN_PER_IP": "5",
            "DEMO_LOGIN_GLOBAL": "999999",
            "DEMO_LOGIN_WINDOW_SECONDS": "120",
        }
    )
    assert service.login_ip.limit == 5 and service.login_ip.seconds == 120
    assert service.login_all.limit == 5000  # 上限
    with pytest.raises(ValueError, match="DEMO_LOGIN_PER_IP"):
        SessionService.from_environment({"POSTGRES_PASSWORD": "unused", "DEMO_LOGIN_PER_IP": "0"})


def test_globally_rejected_requests_leave_no_per_ip_state(
    limited: tuple[SessionService, Clock],
) -> None:
    service, clock = limited
    app = create_app(service)
    for ip in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
        assert post(app, ip).status_code == 201
    before = set(service.login_ip.hits)
    for index in range(5):
        assert post(app, f"10.1.0.{index}").status_code == 429
    assert set(service.login_ip.hits) == before
    clock.now += 61
    assert post(app, "10.1.0.0").status_code == 201


def test_mapped_ipv4_and_ipv6_prefix_share_one_quota(
    limited: tuple[SessionService, Clock], postgres_url: URL
) -> None:
    service, _ = limited
    app = create_app(service)
    assert post(app, "1.2.3.4").status_code == 201
    assert post(app, "::ffff:1.2.3.4").status_code == 201
    assert post(app, "1.2.3.4").status_code == 429
    service2 = SessionService(postgres_url, demo_enabled=True, login_per_ip=1, login_global=50)
    app2 = create_app(service2)
    assert post(app2, "2001:db8:1:2::1").status_code == 201
    assert post(app2, "2001:db8:1:2:ffff::9").status_code == 429

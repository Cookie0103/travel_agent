"""E3/E6：进程内限流原语；时钟可注入，不睡眠。"""

import pytest

from backend.services.rate_limit import SlidingWindow, TokenBucket, positive_int


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_token_bucket_allows_burst_then_refills_steadily() -> None:
    clock = Clock()
    bucket = TokenBucket(burst=3, per_second=1, clock=clock)
    assert [bucket.take("a") for _ in range(3)] == [0, 0, 0]
    wait = bucket.take("a")
    assert 0 < wait <= 1
    assert bucket.take("b") == 0  # 各键独立
    clock.now += 1
    assert bucket.take("a") == 0 and bucket.take("a") > 0
    clock.now += 100  # 空闲后最多回到burst，不累积
    assert [bucket.take("a") for _ in range(3)] == [0, 0, 0] and bucket.take("a") > 0


def test_sliding_window_counts_per_key_and_reports_retry_after() -> None:
    clock = Clock()
    window = SlidingWindow(limit=2, seconds=60, clock=clock)
    assert window.hit("ip1") == 0
    clock.now += 10
    assert window.hit("ip1") == 0
    wait = window.hit("ip1")
    assert wait == pytest.approx(50)  # 最早一次命中滑出窗口还需50秒
    assert window.hit("ip2") == 0
    clock.now += 50.5
    assert window.hit("ip1") == 0  # 第一次已滑出


def test_rejected_hits_do_not_extend_the_window() -> None:
    clock = Clock()
    window = SlidingWindow(limit=1, seconds=60, clock=clock)
    assert window.hit("k") == 0
    for _ in range(10):
        clock.now += 1
        assert window.hit("k") > 0
    clock.now = 1061
    assert window.hit("k") == 0


def test_idle_keys_are_pruned() -> None:
    clock = Clock()
    window = SlidingWindow(limit=1, seconds=60, clock=clock, max_keys=4)
    for index in range(10):
        window.hit(f"k{index}")
        clock.now += 61
    assert len(window.hits) <= 4
    bucket = TokenBucket(burst=1, per_second=1, clock=clock, max_keys=4)
    for index in range(10):
        bucket.take(f"k{index}")
        clock.now += 5
    assert len(bucket.state) <= 4


def test_positive_int_reads_bounded_environment_values() -> None:
    assert positive_int({}, "X", 7, 100) == 7
    assert positive_int({"X": "12"}, "X", 7, 100) == 12
    assert positive_int({"X": "5000"}, "X", 7, 100) == 100  # 上限
    for bad in ("0", "-1", "abc", "1.5"):
        with pytest.raises(ValueError, match="X"):
            positive_int({"X": bad}, "X", 7, 100)


def test_sliding_window_hot_path_does_not_degrade_with_many_active_keys() -> None:
    import time

    from backend.services.rate_limit import SlidingWindow as Window

    def per_hit(count: int) -> float:
        window = Window(limit=5, seconds=600, clock=Clock(), max_keys=1000)
        start = time.perf_counter()
        for index in range(count):
            window.hit(f"k{index}")
        assert len(window.hits) <= 1000  # 内存有界
        return (time.perf_counter() - start) / count

    per_hit(1000)  # 预热
    small, large = per_hit(2000), per_hit(20000)
    assert large < small * 8 + 0.0002  # 每次耗时不随key总数增长（旧实现约百倍）


def test_check_does_not_record_or_create_keys() -> None:
    clock = Clock()
    window = SlidingWindow(limit=1, seconds=60, clock=clock)
    assert window.check("a") == 0 and "a" not in window.hits
    assert window.hit("a") == 0
    assert window.check("a") == pytest.approx(60)
    assert "b" not in window.hits and window.check("b") == 0 and "b" not in window.hits


def test_full_window_evicts_oldest_active_key_not_everything() -> None:
    window = SlidingWindow(limit=5, seconds=600, clock=Clock(), max_keys=3)
    for name in "abcd":
        window.hit(name)
    assert list(window.hits) == ["b", "c", "d"]


def test_client_key_normalizes_addresses() -> None:
    from backend.services.rate_limit import client_key

    assert client_key("::ffff:1.2.3.4") == client_key("1.2.3.4") == "1.2.3.4"
    assert client_key("2001:db8:1:2:aaaa::1") == client_key("2001:db8:1:2:bbbb::9")
    assert client_key("2001:db8:1:2::1") != client_key("2001:db8:1:3::1")
    assert client_key("fe80::1%eth0") == client_key("fe80::2")
    for odd in ("testclient", "", "not an ip"):
        assert client_key(odd) == odd


def test_proxy_headers_are_opt_in_via_forwarded_allow_ips() -> None:
    from backend.server import proxy_options

    assert proxy_options({}) == {"proxy_headers": False}
    assert proxy_options({"FORWARDED_ALLOW_IPS": "  "}) == {"proxy_headers": False}
    assert proxy_options({"FORWARDED_ALLOW_IPS": "10.0.0.5"}) == {
        "proxy_headers": True,
        "forwarded_allow_ips": "10.0.0.5",
    }


def test_checked_but_unrecorded_expired_key_does_not_break_later_hits() -> None:
    """check 清空过期队列后该键未再 hit，其空队列不能让后续其它键的 hit 抛 IndexError。"""
    clock = Clock()
    window = SlidingWindow(2, 10, clock)
    window.hit("A")
    clock.now += 100
    assert window.check("A") == 0
    assert window.hit("B") == 0
    assert window.hit("C") == 0

"""用户贴的乐天链接只解析酒店号；不信任域名以外的内容，不访问网络。"""

import pytest

from backend.domain.rakuten_links import match_hotel_name, rakuten_hotel_numbers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "看 https://hotel.travel.rakuten.co.jp/hotelinfo/plan/?f_no=75325&f_flg=PLAN 很好",
            ("75325",),
        ),
        ("https://img.travel.rakuten.co.jp/image/tr/api/re/gJNfM/?f_hotel_no=192202", ("192202",)),
        ("https://travel.rakuten.co.jp/HOTEL/148889/148889.html", ("148889",)),
        ("https://hotel.travel.rakuten.co.jp/hotelinfo/plan/32075", ("32075",)),
        (
            "https://hb.afl.rakuten.co.jp/hgc/abc/?pc=https%3A%2F%2Ftravel.rakuten.co.jp%2FHOTEL%2F1487%2F",
            ("1487",),
        ),
        ("https://travel.rakuten.co.jp/?f_no=1&x https://travel.rakuten.co.jp/?f_no=2", ("1", "2")),
        ("https://travel.rakuten.co.jp/?f_no=7 https://travel.rakuten.co.jp/?f_no=7", ("7",)),
    ],
)
def test_hotel_numbers_come_from_rakuten_urls(text: str, expected: tuple[str, ...]) -> None:
    assert rakuten_hotel_numbers(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "https://evil.example.com/?f_no=75325",
        "https://rakuten.co.jp.evil.example/?f_no=75325",
        "f_no=75325 没有链接",
        "https://travel.rakuten.co.jp/?f_no=abc",
        "https://travel.rakuten.co.jp/yado/kyoto/kyotoeki.html",
        "",
    ],
)
def test_other_hosts_and_non_numeric_ids_are_ignored(text: str) -> None:
    assert rakuten_hotel_numbers(text) == ()


def test_at_most_three_numbers_are_taken() -> None:
    text = " ".join(f"https://travel.rakuten.co.jp/?f_no={n}" for n in range(1, 8))
    assert rakuten_hotel_numbers(text) == ("1", "2", "3")


NAMES = ("ホテルグランヴィア京都", "京都駅前ホテル", "リーガロイヤルホテル大阪")


def test_name_match_is_normalized_and_must_be_unique() -> None:
    assert match_hotel_name("就住グランヴィア京都吧", NAMES) == 0
    assert match_hotel_name("ホテル グランヴィア 京都", NAMES) == 0
    assert match_hotel_name("リーガロイヤルホテル大阪", NAMES) == 2
    assert match_hotel_name("我想住个好酒店", NAMES) is None
    assert match_hotel_name("京都", NAMES) is None  # 太短，不猜
    assert match_hotel_name("ホテル", NAMES) is None  # 多家都含


def test_ambiguous_names_do_not_match() -> None:
    same = ("ホテルグランヴィア京都", "ホテルグランヴィア京都別館")
    assert match_hotel_name("ホテルグランヴィア京都", same) == 0  # 完整名字优先
    assert match_hotel_name("グランヴィア京", same) is None

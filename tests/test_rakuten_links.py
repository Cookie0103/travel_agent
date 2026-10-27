"""用户贴的乐天链接只解析酒店号；不信任域名以外的内容，不访问网络。"""

import pytest

from backend.domain.rakuten_links import match_hotel_names, rakuten_hotel_numbers


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
REAL = (
    "天然温泉 浪華の湯 ドーミーイン大阪谷町",
    "アパホテル〈大阪肥後橋駅前タワー〉",
    "アパホテル〈京都駅堀川通〉",
    "アパホテル〈京都駅前〉",
)


def hits(text: str, names: tuple[str, ...] = REAL) -> list[int]:
    return match_hotel_names(text, names)


def test_name_match_is_normalized_and_must_be_unique() -> None:
    assert hits("就住グランヴィア京都吧", NAMES) == [0]
    assert hits("ホテル グランヴィア 京都", NAMES) == [0]
    assert hits("リーガロイヤルホテル大阪", NAMES) == [2]
    assert hits("我想住个好酒店", NAMES) == []
    assert hits("京都", NAMES) == []  # 太短，不猜
    assert hits("ホテル", NAMES) == []  # 泛词


def test_distinctive_fragment_picks_the_one_hotel() -> None:
    assert hits("我看乐天上的浪華の湯这家不错，就住这家吧。") == [0]
    assert hits("住ドーミーイン吧") == [0]
    assert hits("大阪谷町那家") == [0]
    assert hits("就住堀川通那家") == [2]
    assert hits("肥後橋") == [1]


def test_brackets_and_width_variants_match_full_name() -> None:
    assert hits("アパホテル<京都駅堀川通>") == [2]
    assert hits("ｱﾊﾟﾎﾃﾙ(京都駅堀川通)") == [2]
    assert hits("アパホテル〈京都駅前〉") == [3]  # 完整名优先，不与堀川通那家混淆
    assert hits("天然温泉浪華の湯ドーミーイン大阪谷町") == [0]


def test_generic_fragments_never_match() -> None:
    for text in ("ホテル", "アパ", "アパホテル", "京都", "大阪", "駅前", "タワー", "inn", "hotel"):
        assert hits(text) == [], text
    assert hits("アパホテル") == []
    assert hits("大阪のホテルがいい") == []


def test_shared_fragment_is_ambiguous() -> None:
    assert hits("京都駅の方がいい") == []  # 京都+駅 都是泛词
    twin = (*REAL, "ドーミーイン京都駅前")
    assert hits("ドーミーインがいい", twin) == [0, 4]
    shared = ("ホテルグランヴィア京都", "ホテルグランヴィア京都別館")
    assert hits("ホテルグランヴィア京都", shared) == [0]  # 完整名字优先
    assert hits("グランヴィア京", shared) == [0, 1]

"""用户贴的乐天链接与酒店名解析；只提取酒店号/做归一化比较，不访问网络、不信任任何其他内容。"""

import re
import unicodedata
from urllib.parse import parse_qsl, unquote, urlsplit

_URL = re.compile(r"https?://[^\s<>\"'「」（）()]+", re.IGNORECASE)
_NUMBER_KEYS = ("f_no", "f_hotel_no", "hotel_no")
_PATHS = (
    re.compile(r"/HOTEL/(\d{1,9})(?:/|$)", re.IGNORECASE),
    re.compile(r"/hotelinfo/plan/(\d{1,9})(?:/|$)", re.IGNORECASE),
)
MAX_NUMBERS = 3
# 空结果时给用户的乐天旅游站点入口；深链搜索格式未离线验证，故只给首页。
RAKUTEN_SEARCH_URL = "https://travel.rakuten.co.jp/"


def _is_rakuten(host: str | None) -> bool:
    host = (host or "").lower().rstrip(".")
    return host == "rakuten.co.jp" or host.endswith(".rakuten.co.jp")


def _numbers(url: str, depth: int) -> list[str]:
    parts = urlsplit(url)
    if not _is_rakuten(parts.hostname):
        return []
    found: list[str] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _NUMBER_KEYS and value.isascii() and value.isdecimal():
            found.append(value)
        elif depth < 2 and value.lower().startswith(("http://", "https://")):
            found.extend(_numbers(unquote(value), depth + 1))  # 联盟跳转：pc=<编码后的落地页>
    for pattern in _PATHS:
        found.extend(match[1] for match in pattern.finditer(parts.path))
    return found


def rakuten_hotel_numbers(text: str) -> tuple[str, ...]:
    """按出现顺序返回去重后的乐天酒店号(最多3个)；只认rakuten.co.jp域名下的URL。"""
    found: list[str] = []
    for url in _URL.findall(text):
        for number in _numbers(url.rstrip(".,;，。"), 0):
            if number not in found:
                found.append(number)
    return tuple(found[:MAX_NUMBERS])


def normalize_name(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    return "".join(ch for ch in folded if unicodedata.category(ch)[0] in "LN")


# 太泛的词：单独出现不足以认定是哪家酒店(城市名另由CITY_ALIASES补充)
GENERIC_TERMS = (
    "ホテル", "アパホテル", "アパ", "駅前", "タワー", "リゾート", "旅館", "温泉", "天然温泉",
    "本館", "別館", "新館", "東館", "西館", "南館", "北館", "公式", "宿泊", "inn", "hotel",
    "resort", "station", "tower", "駅", "前", "店",
)  # fmt: skip
MIN_FRAGMENT = 3  # 片段(归一化后)至少3字
MIN_DISTINCT = 2  # 去掉泛词/城市词后至少还剩2字


def _generic_terms() -> tuple[str, ...]:
    from backend.domain.travel_request import CITY_ALIASES

    cities = {normalize_name(x) for pair in CITY_ALIASES.items() for x in pair}
    terms = {normalize_name(t) for t in GENERIC_TERMS} | cities
    return tuple(sorted((t for t in terms if t), key=len, reverse=True))


def _distinct_length(fragment: str, terms: tuple[str, ...]) -> int:
    for term in terms:
        fragment = fragment.replace(term, "")
    return len(fragment)


def _common_fragments(a: str, b: str) -> set[str]:
    """a、b的所有极大公共子串。"""
    found: set[str] = set()
    previous = [0] * (len(b) + 1)
    for i, x in enumerate(a, 1):
        current = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            if x == y:
                current[j] = previous[j - 1] + 1
                ends = i == len(a) or j == len(b) or a[i] != b[j]
                if ends and current[j] >= MIN_FRAGMENT:
                    found.add(a[i - current[j] : i])
        previous = current
    return found


def match_hotel_names(text: str, names: tuple[str, ...] | list[str]) -> list[int]:
    """用户原话命中的候选下标(可能0个、1个或多个)。

    先看原话是否含某候选的完整归一化名称(取最长者)；否则看原话与候选名共有的、
    至少3字且去掉泛词/城市词后仍有2字以上的连续片段。多个候选命中由调用方当作歧义处理。
    """
    haystack = normalize_name(text)
    wanted = [normalize_name(name) for name in names]
    whole = [i for i, w in enumerate(wanted) if len(w) >= MIN_FRAGMENT and w in haystack]
    if whole:
        longest = max(len(wanted[i]) for i in whole)
        return [i for i in whole if len(wanted[i]) == longest]
    terms = _generic_terms()
    return [
        i
        for i, w in enumerate(wanted)
        if any(_distinct_length(f, terms) >= MIN_DISTINCT for f in _common_fragments(haystack, w))
    ]

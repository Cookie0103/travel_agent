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
MIN_MATCH = 5


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


def _longest_common(a: str, b: str) -> int:
    best = 0
    previous = [0] * (len(b) + 1)
    for x in a:
        current = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            if x == y:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def match_hotel_name(text: str, names: tuple[str, ...] | list[str]) -> int | None:
    """用户原话与已展示候选名称的唯一匹配下标；对不上、太短或有歧义返回None。"""
    haystack = normalize_name(text)
    wanted = [normalize_name(name) for name in names]
    whole = [i for i, name in enumerate(wanted) if len(name) >= MIN_MATCH and name in haystack]
    if whole:
        longest = max(len(wanted[i]) for i in whole)
        best = [i for i in whole if len(wanted[i]) == longest]
        return best[0] if len(set(wanted[i] for i in best)) == 1 else None
    scores = [_longest_common(haystack, name) if len(name) >= MIN_MATCH else 0 for name in wanted]
    top = max(scores, default=0)
    if top < MIN_MATCH:
        return None
    tops = [i for i, score in enumerate(scores) if score == top]
    if len(tops) != 1 or top < 0.6 * len(wanted[tops[0]]):
        return None
    return tops[0]

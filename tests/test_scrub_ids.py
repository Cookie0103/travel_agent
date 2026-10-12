"""最终回复兜底：只删带标签的内部编号与UUID，其余文本不动。"""

import pytest

from backend.agent.persona import travel_prompt
from backend.domain.execution import scrub_internal_ids


def test_prompt_forbids_internal_ids() -> None:
    assert "不得出现offer_id" in travel_prompt()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "ヴィラ京都 6,400 日元（offer_id ff26d6e4…，evidence dcd676bf…）",
            "ヴィラ京都 6,400 日元",
        ),
        (
            "酒店A（offer_id 123e4567-e89b-12d3-a456-426614174000）很好",
            "酒店A很好",
        ),
        ("酒店B (evidence_id=ab12cd34, 6,400 日元)", "酒店B (6,400 日元)"),
        ("draft_id: 9f8e7d6c5b；plan_id 12ab34cd 已保存", " 已保存"),
        ("编号 123e4567-e89b-12d3-a456-426614174000 无标签", "编号  无标签"),
    ],
)
def test_labelled_ids_removed(raw: str, expected: str) -> None:
    assert scrub_internal_ids(raw) == expected
    assert scrub_internal_ids(scrub_internal_ids(raw)) == scrub_internal_ids(raw)


@pytest.mark.parametrize(
    "text",
    [
        "京都两晚，6,400 日元，2026-10-07入住",
        "详情见 https://travel.rakuten.co.jp/HOTEL/123456/ 页面",
        "evidence added decade facade 没有编号；offer_id 字段不展示",
        "evidence defaced 与 plan_id 无关",
        "",
    ],
)
def test_ordinary_text_untouched(text: str) -> None:
    assert scrub_internal_ids(text) == text

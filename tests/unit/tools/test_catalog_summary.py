"""搜索摘要带营业时间，使模型无需为营业时间逐个调用详情工具。"""

from backend.tools.contracts import RESULT_LIMIT
from backend.tools.travel import catalog_summary


def test_summary_keeps_opening_hours_and_drops_unlisted_fields() -> None:
    row: dict[str, object] = {
        "place_id": "p1",
        "name": "寺",
        "opening_hours": "Mon: 09:00-17:00",
        "secret": "x",
    }
    summary = catalog_summary(row)
    assert summary["opening_hours"] == "Mon: 09:00-17:00"
    assert "secret" not in summary


def test_summary_text_stays_bounded_with_opening_hours() -> None:
    row: dict[str, object] = {
        "name": "寺",
        "opening_hours": "Mon: 09:00-17:00",
        "text": "字" * 5000,
    }
    summary = catalog_summary(row)
    assert summary["text_truncated"] is True
    assert len(str(summary)) < RESULT_LIMIT // 8

"""公开快照校验与营业时间失败路径；所有输入均来自本地，无网络调用。"""

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.domain.catalog import Place, Source
from backend.domain.opening_hours import opening_state
from backend.tools.search import PlaceSearchInput, search
from data.import_catalog import SNAPSHOT, load_snapshot


def test_snapshot_has_real_attribution_and_alias_search() -> None:
    entries = load_snapshot()
    places = [e for e in entries if isinstance(e, Place)]
    assert len(places) >= 20 and len(entries) - len(places) >= 12
    assert all(e.source.retrieved_at.utcoffset() is not None for e in entries)
    assert {e.source.license for e in entries} == {"CC-BY-SA-4.0", "ODbL-1.0"}
    named = next(p for p in places if p.aliases)
    rows = [p.model_dump(mode="json") for p in places]
    assert search(rows, PlaceSearchInput(city="Kyoto", query=named.aliases[0]))
    assert not search(rows, PlaceSearchInput(city="大阪", query=named.name))
    assert any(p.opening_hours is None for p in places)
    with pytest.raises(ValidationError):
        Source.model_validate({"provider": "osm", "source_ref": "unknown"})


def test_modified_snapshot_is_rejected_before_import(tmp_path: Path) -> None:
    for name in ("manifest.json", "osm.json", "wikivoyage.json"):
        shutil.copyfile(SNAPSHOT / name, tmp_path / name)
    data = json.loads((tmp_path / "osm.json").read_text(encoding="utf-8"))
    data["elements"] = []
    (tmp_path / "osm.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="校验和"):
        load_snapshot(tmp_path)


@pytest.mark.parametrize(
    ("hours", "start", "end", "expected"),
    [
        ("Mo-Su 09:00-17:00; Mo off", "2026-10-05T10:00+09:00", "2026-10-05T11:00+09:00", "closed"),
        ("Tu-Su 09:00-17:00", "2026-10-06T10:00+09:00", "2026-10-06T11:00+09:00", "open"),
        ("Fr 22:00-02:00", "2026-10-10T00:30+09:00", "2026-10-10T01:30+09:00", "open"),
        ("Fr 22:00-02:00", "2026-10-10T01:30+09:00", "2026-10-10T02:30+09:00", "closed"),
        (
            "Mo-Su 09:00-12:00,13:00-17:00",
            "2026-10-06T11:30+09:00",
            "2026-10-06T13:30+09:00",
            "closed",
        ),
        ("Mo-Su 09:00-17:00", "2026-10-06T07:30+00:00", "2026-10-06T08:00+00:00", "open"),
        (None, "2026-10-06T10:00+09:00", "2026-10-06T11:00+09:00", "unknown"),
        (
            "Mo-Su 09:00-17:00; PH off",
            "2026-10-06T10:00+09:00",
            "2026-10-06T11:00+09:00",
            "unknown",
        ),
        ("Fr 22:00-02:00; Sa off", "2026-10-10T00:30+09:00", "2026-10-10T01:30+09:00", "unknown"),
        ("09:00-25:00", "2026-10-06T10:00+09:00", "2026-10-06T11:00+09:00", "unknown"),
        ("24/7", "2026-10-06T23:00+09:00", "2026-10-07T01:00+09:00", "open"),
    ],
)
def test_opening_hours_checks_entire_visit(
    hours: str | None, start: str, end: str, expected: str
) -> None:
    """R06：未知营业时间不能判通过，跨午夜和闭馆必须有确定结果。"""
    assert (
        opening_state(hours, datetime.fromisoformat(start), datetime.fromisoformat(end)) == expected
    )


def test_naive_visit_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="时区"):
        opening_state("24/7", datetime(2026, 10, 6, 10), datetime(2026, 10, 6, 11))

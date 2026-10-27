"""公开快照校验与营业时间失败路径；所有输入均来自本地，无网络调用。"""

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.domain.catalog import Article, Place, Source
from backend.domain.opening_hours import opening_state
from backend.tools.search import ContentSearchInput, PlaceSearchInput, search
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


def test_each_city_page_keeps_its_own_revision_and_attribution() -> None:
    """每城一页：城市取条目原标题，来源固定到该页版本；简体/英文写法经有限别名检索。"""
    articles = [e for e in load_snapshot() if isinstance(e, Article)]
    pages = json.loads((SNAPSHOT / "manifest.json").read_text(encoding="utf-8"))["files"]
    revisions: dict[str, int] = {}
    for name in pages:
        if name.startswith("wikivoyage"):
            page = json.loads((SNAPSHOT / name).read_text(encoding="utf-8"))["query"]["pages"][0]
            revisions[page["title"]] = page["revisions"][0]["revid"]
    assert len(revisions) == 14 and {a.city for a in articles} == revisions.keys()
    for article in articles:
        revision = revisions[article.city]
        assert article.title.startswith(article.city + " · ")
        assert article.article_id.startswith(f"wv:{revision}:")
        assert (
            article.source.source_ref == f"https://zh.wikivoyage.org/w/index.php?oldid={revision}"
        )
        assert article.source.content_version == str(revision)
        assert f"（{article.city}条目" in article.source.attribution
    assert len({a.article_id for a in articles}) == len(articles)
    assert sum(a.city == "京都" for a in articles) == 20
    rows = [a.model_dump(mode="json") for a in articles]
    aliases = (("东京", "東京"), ("Hiroshima", "廣島"), ("神户", "神戶"), ("镰仓", "镰仓"))
    for city, title in aliases:
        found = search(rows, ContentSearchInput(city=city, limit=8))
        assert found and {row["city"] for row in found} == {title}
    assert not search(rows, ContentSearchInput(city="仙台"))


def test_modified_city_page_is_rejected_before_import(tmp_path: Path) -> None:
    for name in ("manifest.json", "osm.json", *(p.name for p in SNAPSHOT.glob("wikivoyage*"))):
        shutil.copyfile(SNAPSHOT / name, tmp_path / name)
    (tmp_path / "wikivoyage-osaka.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="校验和"):
        load_snapshot(tmp_path)


def test_modified_snapshot_is_rejected_before_import(tmp_path: Path) -> None:
    for name in ("manifest.json", "osm.json", "wikivoyage.json"):
        shutil.copyfile(SNAPSHOT / name, tmp_path / name)
    data = json.loads((tmp_path / "osm.json").read_text(encoding="utf-8"))
    data["elements"] = []
    (tmp_path / "osm.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="校验和"):
        load_snapshot(tmp_path)


def test_source_backed_historical_names_are_searchable_without_renaming_places() -> None:
    """R03：历史名只供检索，不伪造祇园街区目录或攻略。"""
    entries = load_snapshot()
    places = [e for e in entries if isinstance(e, Place)]
    yasaka = next(p for p in places if p.place_id == "osm:way/328903218")
    assert yasaka.name == "八坂神社" and "祇園神社" in yasaka.aliases
    assert "Gion-jinja" in yasaka.aliases
    assert all(";" not in alias for alias in yasaka.aliases)
    rows = [p.model_dump(mode="json") for p in places]
    found = search(rows, PlaceSearchInput(city="京都", query="Gion"))
    assert any(row["place_id"] == yasaka.place_id for row in found)
    assert not search(rows, PlaceSearchInput(city="大阪", query="Gion"))
    assert yasaka.field_sources["aliases"] == yasaka.source.source_ref


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

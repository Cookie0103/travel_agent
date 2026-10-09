"""补充快照是可核对的独立开发数据，不改变原基准或伪造未知字段。"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.domain.catalog import Article, ContentSearchInput, Place, PlaceSearchInput, search
from data.import_catalog import SNAPSHOT, load_snapshot

SUPPLEMENT = SNAPSHOT.parent / "supplements" / "kyoto-matcha-v1"


def test_curated_matcha_entries_match_raw_sources_and_preserve_unknowns() -> None:
    entries = load_snapshot(SUPPLEMENT)
    assert len(entries) == 2
    place = next(e for e in entries if isinstance(e, Place))
    article = next(e for e in entries if isinstance(e, Article))
    osm = json.loads((SUPPLEMENT / "osm.json").read_text(encoding="utf-8"))
    raw = next(e for e in osm["elements"] if e["id"] == 4775546783)
    assert place.osm_id == "node/4775546783" and place.name == raw["tags"]["name"]
    assert (place.latitude, place.longitude) == (raw["lat"], raw["lon"])
    assert set(place.aliases) <= {v for k, v in raw["tags"].items() if k.startswith("name:")}
    assert place.indoor is None and place.opening_hours is None
    assert place.source.content_version.endswith(":curation-v1")
    wiki = json.loads((SUPPLEMENT / "wikivoyage.json").read_text(encoding="utf-8"))
    revision = wiki["query"]["pages"][0]["revisions"][0]["revid"]
    assert article.source.source_ref == f"https://en.wikivoyage.org/w/index.php?oldid={revision}"
    assert article.source.content_version == f"{revision}:curation-v1"
    assert "中文节选改写" in article.source.attribution
    assert article.source.license == "CC-BY-SA-4.0" and place.source.license == "ODbL-1.0"
    assert article.mentioned_places == (place.place_id,)
    assert "未知" in article.text and "历史价格" in article.text
    rows = [e.model_dump(mode="json") for e in entries]
    assert search(rows, ContentSearchInput(city="京都", query="抹茶")) == [rows[1]]
    assert search([rows[0]], PlaceSearchInput(city="京都", query="都路里"))
    assert not search([rows[0]], PlaceSearchInput(city="京都", query="抹茶"))
    assert len(load_snapshot()) == 166


@pytest.mark.parametrize("filename", ["osm.json", "wikivoyage.json", "catalog.json"])
def test_curated_sources_reject_tampering_before_import(tmp_path: Path, filename: str) -> None:
    shutil.copytree(SUPPLEMENT, tmp_path, dirs_exist_ok=True)
    with (tmp_path / filename).open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(ValueError, match="校验和"):
        load_snapshot(tmp_path)


@pytest.mark.parametrize("mutation", ["path", "missing", "empty", "duplicate", "city", "extra"])
def test_invalid_curated_input_never_reaches_database(tmp_path: Path, mutation: str) -> None:
    shutil.copytree(SUPPLEMENT, tmp_path, dirs_exist_ok=True)
    manifest_file = tmp_path / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    catalog_file = tmp_path / "catalog.json"
    rows = json.loads(catalog_file.read_text(encoding="utf-8"))
    if mutation == "path":
        manifest["catalog_file"] = "../../.env"
    elif mutation == "missing":
        catalog_file.unlink()
    else:
        if mutation == "empty":
            rows = []
        elif mutation == "duplicate":
            rows.append(rows[0])
        elif mutation == "city":
            rows[0]["city"] = "大阪"
        else:
            rows[0]["secret"] = "not-allowed"
        catalog_file.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        manifest["files"]["catalog.json"]["sha256"] = hashlib.sha256(
            catalog_file.read_bytes()
        ).hexdigest()
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises((ValueError, ValidationError, FileNotFoundError)):
        load_snapshot(tmp_path)

"""将固定的Wikivoyage/OSM公开快照验证、切段并幂等导入；运行时不联网。"""

import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import AliasPath, AwareDatetime, BaseModel, Field, TypeAdapter

from backend.domain.catalog import Article, Place, Source
from backend.persistence.catalog import import_catalog
from backend.persistence.database import Database, configuration, database_url

SNAPSHOT = Path(__file__).resolve().parent / "snapshots"


class SnapshotFile(BaseModel):
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    retrieved_at: AwareDatetime


class Manifest(BaseModel):
    files: dict[str, SnapshotFile]
    catalog_file: Literal["catalog.json"] | None = None


class Element(BaseModel):
    type: str
    id: int
    lat: float | None = None
    lon: float | None = None
    center: dict[str, float] | None = None
    tags: dict[str, str]


class OSMSnapshot(BaseModel):
    elements: list[Element]
    remark: str | None = None


class WikiSnapshot(BaseModel):
    title: str = Field(validation_alias=AliasPath("query", "pages", 0, "title"))
    extract: str = Field(validation_alias=AliasPath("query", "pages", 0, "extract"))
    revision: int = Field(validation_alias=AliasPath("query", "pages", 0, "revisions", 0, "revid"))


def _source(file: SnapshotFile, provider: str, ref: str, version: str) -> Source:
    osm = provider == "osm"
    return Source(
        provider="osm" if osm else "wikivoyage",
        source_ref=ref,
        content_version=version,
        retrieved_at=file.retrieved_at,
        license="ODbL-1.0" if osm else "CC-BY-SA-4.0",
        license_url="https://opendatacommons.org/licenses/odbl/1-0/"
        if osm
        else "https://creativecommons.org/licenses/by-sa/4.0/",
        attribution="© OpenStreetMap contributors"
        if osm
        else "Wikivoyage contributors（京都条目，作者见来源页历史）",
    )


def places(raw: str, file: SnapshotFile) -> list[Place]:
    snapshot = OSMSnapshot.model_validate_json(raw)
    if snapshot.remark or not snapshot.elements:
        raise ValueError("OSM快照为空或请求未完整完成")
    result: list[Place] = []
    for item in snapshot.elements:
        tags = item.tags
        coordinates = {"lat": item.lat, "lon": item.lon} if item.type == "node" else item.center
        latitude = coordinates.get("lat") if coordinates else None
        longitude = coordinates.get("lon") if coordinates else None
        if latitude is None or longitude is None:
            raise ValueError("OSM缺少坐标，拒绝伪造")
        osm_id = f"{item.type}/{item.id}"
        ref = "https://www.openstreetmap.org/" + osm_id
        source = _source(file, "osm", ref, file.sha256)
        result.append(
            Place(
                place_id="osm:" + osm_id,
                osm_id=osm_id,
                name=tags["name"],
                aliases=tuple(
                    dict.fromkeys(
                        alias.strip()
                        for k, v in tags.items()
                        if k.startswith(("name:", "old_name:"))
                        or k in {"alt_name", "short_name", "old_name"}
                        for alias in v.split(";")
                        if alias.strip()
                    )
                ),
                latitude=latitude,
                longitude=longitude,
                coordinate_kind="node" if item.type == "node" else "bounding_box_center",
                category=tags.get("tourism", tags.get("historic", tags.get("amenity", "unknown"))),
                indoor={"yes": True, "no": False}.get(tags.get("indoor", "")),
                opening_hours=tags.get("opening_hours"),
                source=source,
                field_sources={
                    field: ref
                    for field in (
                        "name",
                        "aliases",
                        "coordinates",
                        "category",
                        "indoor",
                        "opening_hours",
                    )
                },
            )
        )
    return result


def articles(raw: str, file: SnapshotFile) -> list[Article]:
    snapshot = WikiSnapshot.model_validate_json(raw)
    source = _source(
        file,
        "wikivoyage",
        f"https://zh.wikivoyage.org/w/index.php?oldid={snapshot.revision}",
        str(snapshot.revision),
    )
    result: list[Article] = []
    section = "概览"
    for block in re.split(r"\n\s*\n", snapshot.extract):
        lines = block.strip().splitlines()
        if not lines:
            continue
        if lines[0].startswith("=="):
            section = lines.pop(0).strip("= ")
        text = "\n".join(lines).strip()
        if not text:
            continue
        digest = hashlib.sha256((section + "\n" + text).encode("utf-8")).hexdigest()[:16]
        result.append(
            Article(
                article_id=f"wv:{snapshot.revision}:{digest}",
                title=f"{snapshot.title} · {section}",
                text=text,
                source=source,
            )
        )
    if not result:
        raise ValueError("攻略快照没有可导入段落")
    return result


def load_snapshot(folder: Path = SNAPSHOT) -> list[Place | Article]:
    manifest = Manifest.model_validate_json((folder / "manifest.json").read_text(encoding="utf-8"))
    raw: dict[str, str] = {}
    names = ("osm.json", "wikivoyage.json") + (
        (manifest.catalog_file,) if manifest.catalog_file else ()
    )
    for name in names:
        content = (folder / name).read_bytes()
        file = manifest.files.get(name)
        if file is None or hashlib.sha256(content).hexdigest() != file.sha256:
            raise ValueError("快照校验和不符；先核对来源，不能静默导入修改数据")
        raw[name] = content.decode("utf-8")
    if manifest.catalog_file:
        entries = TypeAdapter(list[Place | Article]).validate_json(raw[manifest.catalog_file])
        ids = [e.place_id if isinstance(e, Place) else e.article_id for e in entries]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("整理目录为空或存在重复ID，拒绝导入")
        if any(entry.city != "京都" for entry in entries):
            raise ValueError("当前固定快照仅覆盖京都，整理目录城市不符")
        return entries
    return [
        *places(raw["osm.json"], manifest.files["osm.json"]),
        *articles(raw["wikivoyage.json"], manifest.files["wikivoyage.json"]),
    ]


async def main(folder: Path = SNAPSHOT) -> None:
    entries = load_snapshot(folder)
    database = Database(database_url(configuration()))
    try:
        async with database.sessions.begin() as db:
            count = await import_catalog(db, entries)
        print(json.dumps({"status": "ok", "entries_processed": count, "data_mode": "snapshot"}))
    finally:
        await database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=SNAPSHOT)
    arguments = parser.parse_args()
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(main(arguments.snapshot_dir))

"""文档地图失败必须可修复：缺文件、断链、越界链接不能静默通过。"""

from pathlib import Path

from scripts.check_docs import check_documents


def test_missing_document_and_broken_or_outside_links_are_reported(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("[缺失](missing.md)\n[越界](../outside.md)\n", encoding="utf-8")
    errors = check_documents(tmp_path, ("AGENTS.md", "ARCHITECTURE.md"))
    assert len(errors) == 3
    assert any("missing.md" in error for error in errors)
    assert any("越界" in error or "outside.md" in error for error in errors)
    assert any("入口缺失" in error for error in errors)


def test_short_map_resolves_local_links_without_fetching_external_sources(tmp_path: Path) -> None:
    (tmp_path / "目录.md").write_text("# 标题\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(
        "[领域](%E7%9B%AE%E5%BD%95.md#标题)\n[官网](https://openai.com/index/harness-engineering/)\n",
        encoding="utf-8",
    )
    assert check_documents(tmp_path, ("AGENTS.md",)) == []


def test_map_size_limit_keeps_details_out_of_entry_document(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("地图\n" * 101, encoding="utf-8")
    assert "超过100行" in check_documents(tmp_path, ("AGENTS.md",))[0]

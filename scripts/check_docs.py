"""轻量文档地图检查：入口保持短、仓库内链接存在；不扫描历史日志或私有缓存。"""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    "AGENTS.md",
    "ARCHITECTURE.md",
    "docs/README.md",
    "docs/DESIGN.md",
    "docs/FRONTEND.md",
    "docs/QUALITY_SCORE.md",
    "docs/RELIABILITY.md",
    "docs/SECURITY.md",
    "docs/execution/workflow.md",
    "docs/execution/standards.md",
)
LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")


def check_documents(root: Path, documents: tuple[str, ...] = DOCUMENTS) -> list[str]:
    errors: list[str] = []
    for name in documents:
        path = root / name
        if not path.is_file():
            errors.append(f"{name}: 文档入口缺失")
            continue
        content = path.read_text(encoding="utf-8")
        if name in {"AGENTS.md", "ARCHITECTURE.md"} and len(content.splitlines()) > 100:
            errors.append(f"{name}: 地图超过100行，请把细则移入docs并链接")
        for link in LINK.findall(content):
            reference = urlsplit(link.strip("<>"))
            if reference.scheme or not reference.path:
                continue
            target = (path.parent / unquote(reference.path)).resolve()
            if not target.is_relative_to(root.resolve()) or not target.exists():
                errors.append(f"{name}: 无效仓库链接 {link}；修正入口或补齐目标")
    return errors


def main() -> int:
    errors = check_documents(ROOT)
    for error in errors:
        print(error)
    if not errors:
        print(f"文档地图检查通过：{len(DOCUMENTS)}份入口及其仓库链接")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())

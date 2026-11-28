"""有来源的景点名称等价判断，固定使用 Unicode 的单目标简化映射。"""

from pathlib import Path
from unicodedata import normalize


def _simplified_variants() -> dict[int, int]:
    variants = {}
    for line in (
        Path(__file__).with_name("place_name_variants.txt").read_text(encoding="utf-8").splitlines()
    ):
        if line and not line.startswith("#"):
            traditional, simplified = line.split()
            variants.update(str.maketrans(traditional, simplified))
    return variants


_SIMPLIFIED = _simplified_variants()


def place_name_key(name: str) -> str:
    return "".join(normalize("NFKC", name).translate(_SIMPLIFIED).casefold().split())

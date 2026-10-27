"""Windows 默认 Proactor 循环与 psycopg 异步不兼容：连库的脚本与测试必须显式用 Selector 循环。"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKED = [
    *sorted((ROOT / "scripts").glob("*.py")),
    *sorted((ROOT / "tests/integration").glob("*.py")),
]


def bare_loops(path: Path) -> list[int]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if not (isinstance(owner, ast.Name) and owner.id == "asyncio"):
            continue
        keywords = {item.arg for item in node.keywords}
        if node.func.attr == "run" or (
            node.func.attr == "Runner" and "loop_factory" not in keywords
        ):
            found.append(node.lineno)
    return found


def test_script_and_integration_entrypoints_choose_selector_loop() -> None:
    offenders = {
        str(path.relative_to(ROOT)): lines for path in CHECKED if (lines := bare_loops(path))
    }
    assert offenders == {}

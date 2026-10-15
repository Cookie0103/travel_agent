"""生成契约的漂移检测；不能让前端静默使用过时API对象。"""

import json
from pathlib import Path

from scripts.export_web_schema import schema


def test_committed_web_contract_matches_application_and_output_models() -> None:
    path = Path(__file__).resolve().parents[1] / "data/contracts/web-openapi.json"
    assert json.loads(path.read_text(encoding="utf-8")) == schema()

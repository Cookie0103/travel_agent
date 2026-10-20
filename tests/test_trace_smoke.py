"""联验从目标run的本地span取计费证据，不能把全局账本差值归到单轮。"""

import json
from pathlib import Path

from scripts.smoke_langfuse_linkage import local_measurement


def test_local_measurement_uses_sdk_span_accounted_in_original_currency(tmp_path: Path) -> None:
    target = tmp_path / "trace.jsonl"
    target.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"name": "travel.run", "attributes": {}},
                {
                    "name": "agent.sdk",
                    "attributes": {
                        "travel.currency": "CNY",
                        "travel.http_attempts": 3,
                        "travel.run_accounted": "0.078608",
                    },
                },
            ]
        ),
        encoding="utf-8",
    )
    assert local_measurement(target) == (3, "0.078608")

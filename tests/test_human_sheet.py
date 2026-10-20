"""F9：实际回答原文保留，去重偏向失败样本，人工栏永远留空。"""

import csv
import hashlib
import json
from pathlib import Path

import pytest

from eval.human_sheet import prepare_sheet


def test_readable_sheet_keeps_twenty_four_cases_and_exact_answer(tmp_path: Path) -> None:
    source = tmp_path / "human-labels.csv"
    with source.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["sample_id", "case_id", "task", "conditions", "answer"]
        )
        writer.writeheader()
        for i in range(30):
            writer.writerow(
                {
                    "sample_id": f"sample-{i}",
                    "case_id": f"case-{i % 24}",
                    "task": "比较京都酒店\n用户动作 choice: 保持预算1万；选项 keep",
                    "conditions": json.dumps(
                        {
                            "city": "京都",
                            "start_date": "2026-11-03",
                            "end_date": "2026-11-04",
                            "adults": 2,
                            "rooms": 1,
                            "lodging_budget": {"amount": {"upper": "10000"}},
                        }
                    ),
                    "answer": f"实际回复{i}，cause: budget\n原文不改。",
                }
            )
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    provisional = tmp_path / "agent-provisional.json"
    provisional.write_text(
        json.dumps(
            {
                "csv_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "samples": [{"sample_id": "sample-24", "agent_pass": 0}],
            }
        ),
        encoding="utf-8",
    )
    target = prepare_sheet(source, manifest, provisional, tmp_path / "out")
    rows = list(csv.DictReader(target.open(encoding="utf-8-sig", newline="")))
    assert len(rows) == 24
    assert rows[0]["AI的最后回复"] == "实际回复24，cause: budget\n原文不改。"
    assert "cause" in rows[0]["名词解释"]
    assert all("测试数据" in r["场景说明"] and "2个大人" in r["场景说明"] for r in rows)
    assert all("保持预算1万" in r["你做过的操作"] for r in rows)
    for row in rows:
        for name in ("场景说明", "你做过的操作"):
            assert not any(
                word in row[name]
                for word in ("{", "keep", "revision", "cause", "trace", "applied_upper")
            )
        assert all(
            row[k] == ""
            for k in ("Q1按要求做了吗", "Q2说得清楚不矛盾吗", "Q3知道下一步吗", "不确定", "备注")
        )
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        prepare_sheet(source, manifest, provisional, target.parent)
    assert target.read_bytes() == before


def test_sheet_refuses_prelabels_from_a_different_source(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("sample_id,case_id,task,conditions,answer\na,b,c,{},d\n", encoding="utf-8")
    manifest, provisional = tmp_path / "manifest.json", tmp_path / "provisional.json"
    manifest.write_text("{}", encoding="utf-8")
    provisional.write_text('{"csv_sha256":"wrong","samples":[]}', encoding="utf-8")
    with pytest.raises(ValueError):
        prepare_sheet(source, manifest, provisional, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_technical_terms_in_answer_receive_plain_chinese_explanations() -> None:
    from eval.human_sheet import terms_explanation

    terms = (
        "upstream_empty",
        "relaxation",
        "UTC",
        "HTTP",
        "fixture",
        "budget_relaxation",
        "unknown",
    )
    explanation = terms_explanation("、".join(terms))
    assert all(term + "：" in explanation for term in terms)
    assert terms_explanation("请在页面选择标准节奏") == ""

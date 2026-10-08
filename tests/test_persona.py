"""角色规则与提示词同源；缺人工/模型记录不能伪造校准完成。"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.agent.persona import load_persona, travel_prompt
from eval.persona import JudgeScore, Sample, calibration, rules


def test_persona_is_shared_by_prompt_and_rule_grader() -> None:
    spec, text = load_persona()
    assert text in travel_prompt() and spec.version == "neutral-v1"
    assert all(rules("目前只支持京都，你愿意考虑京都吗？").values())
    assert not rules("字" * (spec.max_characters + 1))["length"]
    assert not rules("哈哈，赶紧去旅行吧！", emotional=True)["no_forbidden_phrases"]


def test_missing_persona_rules_rejected(tmp_path: Path) -> None:
    path = tmp_path / "persona.md"
    path.write_text("没有结构化规则", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_persona(path)


@pytest.mark.parametrize(
    "raw", ['{"score":6,"reason":"越界"}', '{"score":true,"reason":"假数值"}', "not-json"]
)
def test_invalid_judge_output_is_not_a_score(raw: str) -> None:
    with pytest.raises(ValidationError):
        JudgeScore.model_validate_json(raw)
    result = calibration(
        [Sample(case_id="bad", user_input="问题", text="回答", judge_response=raw)]
    )
    assert result["judge_errors"] == 1 and result["within_one_rate"] is None


def test_missing_human_or_temperature_proof_stays_pending() -> None:
    sample = Sample(
        case_id="one",
        user_input="京都哪里能避雨？",
        text="回答",
        judge_response='{"score":4,"reason":"简洁"}',
        judge_model="scripted",
    )
    assert calibration([sample])["judge_errors"] == 1
    assert calibration([sample.model_copy(update={"judge_temperature": 0})])["paired"] == 0


def test_calibration_computes_real_pairs_without_filling_missing_scores() -> None:
    samples = [
        Sample(
            case_id=f"case-{i}",
            user_input="问题",
            text="回答",
            human_score=3,
            human_rater="synthetic-test",
            judge_response=json.dumps({"score": 4, "reason": "测试"}),
            judge_model="scripted",
            judge_temperature=0,
        )
        for i in range(20)
    ]
    result = calibration(samples)
    assert result["status"] == "calibrated" and result["within_one_rate"] == 1
    assert result["exact_rate"] == 0
    with pytest.raises(ValueError, match="重复"):
        calibration([samples[0], samples[0]])

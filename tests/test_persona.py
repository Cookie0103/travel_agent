"""角色规则与提示词同源；缺人工/模型记录不能伪造校准完成。"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.agent.persona import load_persona, travel_prompt
from backend.domain.itinerary import ProposedItem
from backend.tools.travel import DEFINITIONS
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


def test_unspoken_pace_is_assumed_standard_but_never_recorded_as_user_fact() -> None:
    prompt = travel_prompt()
    assert "未说明节奏按标准" not in prompt
    assert "节奏不确定/没答时不写入request，按标准安排" in prompt
    assert "不把它写成用户事实或explicit_fields" in prompt
    assert "节奏未说明时不追问、不发卡" not in prompt  # 节奏现在由合并选择卡询问


def test_chinese_explanations_preserve_original_proper_names() -> None:
    prompt = travel_prompt()
    assert "状态、错误与解释使用中文" in prompt
    assert "酒店、景点的日文专有名称保留原文" in prompt


def test_multi_city_prompt_uses_segments_and_labels_unqueried_transfer_suggestions() -> None:
    prompt = travel_prompt()
    assert "segment_arrive" in prompt and "hotel_stays" in prompt
    assert "城市原文" in prompt and "转场建议" in prompt
    assert "未查询的车次、耗时、票价" in prompt
    assert "pace_too_sparse" in prompt and "visit_duration_range" in prompt
    hotel = next(tool for tool in DEFINITIONS if tool.name == "search_hotel_offers")
    assert "segment_arrive" in hotel.description and "hotel_stays" in hotel.description


def test_item_intro_uses_one_shared_ai_notice_instead_of_repeated_note_markers() -> None:
    assert "非来源核实" not in travel_prompt()
    assert ProposedItem.model_fields["note"].description == "一句话简介"


def test_repair_cap_guidance_preserves_presentation_and_needed_candidate_search() -> None:
    from backend.providers.claude_agent.database_tools import NEXT_STEPS

    prompt = travel_prompt()
    assert "达到修复上限就说明剩余冲突，不继续调用" not in prompt
    assert "额度用完后" in prompt and "已暂存的草稿" in prompt
    assert "候选数量不足" in NEXT_STEPS["itinerary"]
    assert "stage_plan_change" in NEXT_STEPS["itinerary"]


def test_patch_tool_explains_front_insert_order_to_avoid_reversed_days() -> None:
    tool = next(tool for tool in DEFINITIONS if tool.name == "stage_plan_change")
    schema = json.loads(json.dumps(tool.schema))
    description = schema["$defs"]["AddItem"]["properties"]["after_item_id"].get("description", "")
    assert "首部" in description and "逆序" in description
    assert "同一" in description and "执行顺序" in description


def test_prompt_asks_once_then_waits_for_the_user_to_select_hotels() -> None:
    prompt = travel_prompt()
    phrases = (
        "单城市就是一个住宿段",
        "合并选择卡",
        "请在卡片里一次确认",
        "不要在文字里问卡片已覆盖的内容",
        "绝不自动替用户选酒店",
        "select_hotel_from_chat",
        "先不选酒店，先排行程",
        "超出预算约X%",
        "抵达/离开时间不确定按全天安排",
        "也不写入hard_constraints",
        "不要重复搜索，不要卡住流程",
    )
    for phrase in phrases:
        assert phrase in prompt
    # 撤销第2轮：不再自动选最便宜的一家、不再同一轮暂存草稿
    for gone in (
        "一轮做完",
        "同一轮完成",
        "价格最低且最贴近预算的一家",
        "单城市直接用",
        "节奏未说明时留空",
    ):
        assert gone not in prompt
    assert "绝不为此追问或发卡阻塞查询" not in prompt

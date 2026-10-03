"""角色规则、评审输入/解析与人工校准；不把规则分或模型分当成人工评分。"""

import argparse
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.agent.persona import RUBRIC as RUBRIC
from backend.agent.persona import load_persona, persona_judge_prompt


class JudgeScore(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    score: int = Field(ge=0, le=5)
    reason: str = Field(min_length=1, max_length=500)


class Sample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(min_length=1, max_length=100)
    user_input: str = Field(min_length=1)
    text: str = Field(min_length=1)
    scene: Literal["regular", "emotional", "out_of_scope"] = "regular"
    human_score: int | None = Field(default=None, ge=0, le=5, strict=True)
    human_rater: str | None = None
    judge_response: str | None = None
    judge_model: str | None = None
    judge_temperature: int | None = Field(default=None, strict=True)


def rules(text: str, *, emotional: bool = False) -> dict[str, bool]:
    spec, _ = load_persona()
    banned = spec.forbidden_phrases + (spec.emotional_forbidden if emotional else ())
    sentences = [s for s in re.split(r"[。！？!?]+", text) if s.strip()]
    options = re.findall(r"(?m)^\s*(?:[-*]|\d+[.)、])\s*\S", text)
    return {
        "length": len(text) <= spec.max_characters,
        "sentences": len(sentences) <= spec.max_sentences,
        "options": len(options) <= spec.max_options,
        "no_forbidden_phrases": not any(phrase in text for phrase in banned),
        "plain_format": not re.search(r"(?m)^#{1,6}\s|```", text),
    }


def judge_prompt(sample: Sample) -> str:
    return (
        persona_judge_prompt()
        + "\n待评数据：\n"
        + json.dumps(
            {"scene": sample.scene, "user_input": sample.user_input, "candidate": sample.text},
            ensure_ascii=False,
        )
    )


def calibration(samples: list[Sample]) -> dict[str, object]:
    if len({s.case_id for s in samples}) != len(samples):
        raise ValueError("校准case_id重复")
    pairs: list[tuple[int, int]] = []
    errors = 0
    models: set[str] = set()
    for sample in samples:
        if sample.judge_response is None:
            continue
        try:
            score = JudgeScore.model_validate_json(sample.judge_response)
        except ValidationError:
            errors += 1
            continue
        if not sample.judge_model or sample.judge_temperature != 0:
            errors += 1
            continue
        models.add(sample.judge_model)
        if sample.human_score is not None and sample.human_rater and sample.human_rater.strip():
            pairs.append((score.score, sample.human_score))
    enough = len(pairs) >= 20 and len(models) == 1 and errors == 0
    return {
        "status": "calibrated" if enough else "pending",
        "samples": len(samples),
        "paired": len(pairs),
        "judge_errors": errors,
        "judge_models": sorted(models),
        "within_one_rate": sum(abs(a - b) <= 1 for a, b in pairs) / len(pairs) if pairs else None,
        "exact_rate": sum(a == b for a, b in pairs) / len(pairs) if pairs else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="读取真实人工/评审记录计算校准；本入口不调用模型")
    parser.add_argument("samples", type=Path)
    args = parser.parse_args()
    try:
        samples = [
            Sample.model_validate_json(line)
            for line in args.samples.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        print(json.dumps(calibration(samples), ensure_ascii=False))
    except (ValueError, OSError):
        print("校准记录格式错误，未生成评分。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

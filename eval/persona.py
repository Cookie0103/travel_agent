"""角色规则、评审输入/解析与人工校准；不把规则分或模型分当成人工评分。"""

import argparse
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.agent.persona import RUBRIC as RUBRIC
from backend.agent.persona import load_persona
from eval.content import HumanQuality, QualityScore
from scripts.dev import configure_environment


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
    human_quality: HumanQuality | None = None
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


def content_calibration(samples: list[Sample]) -> dict[str, object]:
    dimensions: dict[str, dict[str, object]] = {}
    for dimension in ("relevance", "explanation", "tradeoffs"):
        projected: list[Sample] = []
        for sample in samples:
            response = sample.judge_response
            if response is not None:
                try:
                    quality = QualityScore.model_validate_json(response)
                    response = JudgeScore(
                        score=getattr(quality, dimension), reason=dimension
                    ).model_dump_json()
                except ValidationError:
                    # 语气score JSON也不能当合法三维分，原样本不变，投影计error。
                    response = "invalid-content-score"
            human = sample.human_quality
            projected.append(
                sample.model_copy(
                    update={
                        "judge_response": response,
                        "human_score": getattr(human, dimension) if human else None,
                        "human_rater": human.rater if human else None,
                    }
                )
            )
        dimensions[dimension] = calibration(projected)
    return {
        "status": "calibrated"
        if all(d["status"] == "calibrated" for d in dimensions.values())
        else "pending",
        "dimensions": dimensions,
        "limitations": "内容模型分不证明事实准确；真人三维配对分别校准",
    }


def main() -> int:
    configure_environment()
    parser = argparse.ArgumentParser(description="读取真实人工/评审记录计算校准；本入口不调用模型")
    parser.add_argument("samples", type=Path)
    parser.add_argument("--kind", choices=["persona", "content"], default="persona")
    args = parser.parse_args()
    try:
        samples = [
            Sample.model_validate_json(line)
            for line in args.samples.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        result = calibration(samples) if args.kind == "persona" else content_calibration(samples)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError):
        print("校准记录格式错误，未生成评分。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

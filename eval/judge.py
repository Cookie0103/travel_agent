"""语气评审入口：同一受控SDK、固定模型/温度，逐样本落盘；不生成真人分数。"""

import argparse
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import TextIO
from uuid import uuid4

from pydantic import ValidationError

from backend.agent.persona import persona_judge_prompt
from backend.domain.execution import RunContext
from backend.providers.claude_agent.live import check_evaluation_size, run_live
from backend.providers.claude_agent.settings import load_runtime_settings
from backend.providers.probe.settings import ProbeError
from eval.persona import JudgeScore, Sample, calibration
from eval.run import manifest

ROOT = Path(__file__).resolve().parents[1]


def load_samples(path: Path) -> list[Sample]:
    samples = [
        Sample.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not 1 <= len(samples) <= 30 or len({s.case_id for s in samples}) != len(samples):
        raise ValueError("语气评审需要1至30条唯一case_id")
    if any(s.judge_response is not None or s.judge_model is not None for s in samples):
        raise ValueError("已有评分不能自动重新付费评审")
    return samples


def score_report(sample: Sample, report: dict[str, object], model: str) -> tuple[Sample, str]:
    """先确认实际运行/温度/身份，再解析JSON；格式错误不计入语气分母。"""
    requests, identity, events = (
        report.get("requests"),
        report.get("identity"),
        report.get("events"),
    )
    if (
        report.get("status") != "success"
        or report.get("guard_failures") != []
        or not isinstance(identity, dict)
        or identity.get("provider") != "deepseek"
        or identity.get("model") != model
        or not isinstance(requests, list)
        or not requests
        or report.get("http_attempts") != len(requests)
        or any(
            not isinstance(r, dict)
            or type(r.get("temperature")) is not int
            or r["temperature"] != 0
            for r in requests
        )
        or not isinstance(events, list)
        or any(not isinstance(e, dict) or e.get("kind") == "tool_started" for e in events)
    ):
        return sample, "runtime_error"
    results = report.get("results")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        return sample, "runtime_error"
    outcome = results[0].get("outcome")
    if (
        not isinstance(outcome, dict)
        or outcome.get("code")
        or not isinstance(outcome.get("text"), str)
    ):
        return sample, "runtime_error"
    response = outcome["text"]
    scored = sample.model_copy(
        update={"judge_response": response, "judge_model": model, "judge_temperature": 0}
    )
    try:
        JudgeScore.model_validate_json(response)
    except ValidationError:
        return scored, "judge_error"
    return scored, "scored"


def record(handle: TextIO, row: dict[str, object]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def evaluate(samples: list[Sample], root: Path) -> Path:
    check_evaluation_size(root, len(samples))
    settings = load_runtime_settings(os.environ)
    if settings.provider != "deepseek":
        raise ProbeError("blocked", "固定温度语气评审仅核验DeepSeek")
    directory = root / ".cache" / "persona" / str(uuid4())
    directory.mkdir(parents=True)
    content = "\n".join(s.model_dump_json() for s in samples)
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                **manifest([], ()),
                "purpose": "persona_judge",
                "model": settings.model,
                "temperature": 0,
                "sample_count": len(samples),
                "samples_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "rubric_sha256": hashlib.sha256(persona_judge_prompt().encode()).hexdigest(),
                "max_http_attempts_per_sample": 4,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )
    with (
        (directory / "attempts.jsonl").open("w", encoding="utf-8", newline="\n") as attempts,
        (directory / "results.jsonl").open("w", encoding="utf-8", newline="\n") as results,
        (directory / "samples.jsonl").open("w", encoding="utf-8", newline="\n") as output,
    ):
        stopped = False
        for sample in samples:
            if stopped:
                record(results, {"case_id": sample.case_id, "status": "not_run"})
                continue
            context = RunContext(uuid4())
            record(attempts, {"case_id": sample.case_id, "context": asdict(context)})
            prompt = json.dumps(
                {"scene": sample.scene, "user_input": sample.user_input, "candidate": sample.text},
                ensure_ascii=False,
            )
            try:
                report = run_live(prompt, context, root, persona_judge=True)
                scored, status = score_report(sample, report, settings.model)
            except ProbeError:
                report, scored, status = {}, sample, "runtime_error"
            stopped = status == "runtime_error"
            record(output, scored.model_dump(mode="json"))
            record(
                results,
                {
                    "case_id": sample.case_id,
                    "status": status,
                    "context": asdict(context),
                    "http_attempts": report.get("http_attempts"),
                    "currency": report.get("currency"),
                    "cost_upper": report.get("run_accounted"),
                    "trace_id": report.get("trace_id"),
                    "identity": report.get("identity"),
                },
            )
    return directory


def main() -> int:
    parser = argparse.ArgumentParser(description="固定温度语气评审；默认准备，--live才收费")
    parser.add_argument("samples", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    try:
        samples = load_samples(args.samples)
        if not args.live:
            print(json.dumps({"status": "prepared", "samples": len(samples), "http_attempts": 0}))
            return 0
        directory = evaluate(samples, ROOT)
        scored = [
            Sample.model_validate_json(line)
            for line in (directory / "samples.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        rows = [
            json.loads(line)
            for line in (directory / "results.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        counts = {
            kind: sum(r["status"] == kind for r in rows)
            for kind in ("scored", "judge_error", "runtime_error", "not_run")
        }
        print(
            json.dumps(
                {**calibration(scored), "attempt_results": counts, "directory": str(directory)},
                ensure_ascii=False,
            )
        )
        return int(bool(counts["runtime_error"] or counts["not_run"]))
    except (ValueError, OSError, ProbeError):
        print("评审输入/运行不可用；未生成成功分数，已有费用以账本与attempts为准。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

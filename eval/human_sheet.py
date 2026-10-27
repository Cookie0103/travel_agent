"""把既有回答整理为中文盲标表；原文不改、不调用模型、不写真人标签。"""

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / ".cache/batch-2026-10-13/calibration"
FIELDS = (
    "编号",
    "场景说明",
    "你当时的要求",
    "你做过的操作",
    "AI的最后回复",
    "名词解释",
    "Q1按要求做了吗",
    "Q2说得清楚不矛盾吗",
    "Q3知道下一步吗",
    "不确定",
    "备注",
)
TERMS = {
    "cause": "查询没有合适结果的原因",
    "revision": "旅行条件的版本编号",
    "applied_upper": "建议放宽后的预算上限",
    "choice_card": "本轮有没有展示选择卡",
    "data_mode": "资料来自实际接口还是测试数据",
    "trace": "用于排查这一轮执行的记录编号",
    "upstream_empty": "酒店接口没有返回候选结果",
    "relaxation": "扩大搜索预算范围后的说明",
    "UTC": "统一世界时间，日本时间比它快九小时",
    "HTTP": "程序向外部接口发送的一次请求",
    "fixture": "用于测试的虚构资料",
    "budget_relaxation": "预算放宽建议的类别名称，不代表页面上已有这张卡",
    "unknown": "资料不足，尚未核实",
}
GUIDE = """# 怎么标

每行只读场景、要求、你做过的操作和AI最后回复，再填三个问题的「是」或「否」。名词解释帮助理解原回复中的技术词；这些词是否让你困惑，也由Q2判断。

1. 按要求做了吗：有没有完成要求、有没有未经同意替你改预算或记偏好、有没有在你拒绝后继续推？
2. 说得清楚不矛盾吗：你能理解发生了什么，前后说法是否一致？
3. 知道下一步吗：知道接下来该做什么或该点什么？任务已结束且说明清楚，也可以填是。

三题都是「是」为通过，任一题「否」为不通过。拿不准就在「不确定」填「是」或留题目空白，并在备注说明；这些行不计入统计。不要硬猜。没有真人预填，也没有AI评分提示。

酒店和景点都是虚构测试资料，你不需要核实真实价格和地点。请判断这条回答是否听懂了你的要求、会不会让你困惑或误导。不要先看对照表。

## 示例1：通过
你希望长期避免长距离步行，但尚未决定交通方式。AI提出待确认的步行偏好，说明未记录交通方式、未开始规划，并让你点确认。三题都填是。

## 示例2：不通过
AI说放宽到三倍也没有合适方案，却又让你点预算卡接受放宽，实际页面根本没有这张卡。Q2填否。这与「先扩大检索，用户接受后才改正式预算」不同，后者是正常流程。

## 示例3：不通过
你已经点了保持预算一万，AI仍重复让你接受同一笔两万的放宽。Q1填否。

完成后告诉执行者，执行者负责统计。有效行至少20条才计算一致率与κ，少于20仍为待完成；没有结论时不编分数。
"""


def object_map(value: object) -> dict[str, object]:
    return {k: v for k, v in value.items() if isinstance(k, str)} if isinstance(value, dict) else {}


def terms_explanation(answer: str) -> str:
    return "；".join(f"{word}：{meaning}" for word, meaning in TERMS.items() if word in answer)


def scene(raw: str) -> str:
    conditions = object_map(json.loads(raw))
    initial = object_map(conditions.get("initial_state"))
    request = object_map(initial.get("request")) or conditions
    parts = []
    if request.get("city"):
        parts.append(str(request["city"]))
    if request.get("start_date"):
        parts.append(f"{request['start_date']}起的旅行")
    if request.get("end_date"):
        parts.append(f"到{request['end_date']}结束")
    if request.get("adults"):
        parts.append(f"{request['adults']}个大人")
    if request.get("rooms"):
        parts.append(f"{request['rooms']}间房")
    budget = object_map(request.get("lodging_budget"))
    upper = object_map(budget.get("amount")).get("upper")
    if upper is not None:
        basis = {
            "total": "住宿总预算",
            "per_room_night": "每间每晚预算",
            "per_person_night": "每人每晚预算",
        }.get(str(budget.get("basis", "per_room_night")), "住宿预算")
        parts.append(f"{basis}不超过{upper}日元")
    constraints = request.get("hard_constraints")
    if isinstance(constraints, list):
        parts.extend(
            v
            for v in constraints
            if isinstance(v, str) and v.startswith(("住宿：", "房型：", "床型："))
        )
    return (
        "（测试数据，酒店和景点都是虚构的）"
        + ("，".join(parts) if parts else "旅行偏好或对话确认，具体要求见下一列")
        + "。"
    )


def task_and_actions(task: str) -> tuple[str, str]:
    pieces = re.split(r"\n用户动作 ", task)
    labels = {
        "message": "你说",
        "choice": "你点击了选择卡",
        "hotels": "你选择了住宿",
        "new_session": "你打开新会话",
        "confirm_plan": "你确认了行程",
        "done": "你结束对话",
    }
    actions = []
    for piece in pieces[1:]:
        kind, _, text = piece.partition(":")
        text = re.sub(r"；选项 \S+", "", text).strip()
        actions.append(labels.get(kind, "你继续操作") + "：" + text)
    return pieces[0], "\n".join(actions) or "尚未点击；这是当前这轮要求。"


def prepare_sheet(source: Path, manifest: Path, provisional: Path, directory: Path) -> Path:
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    prelabels = object_map(json.loads(provisional.read_text(encoding="utf-8")))
    if prelabels.get("csv_sha256") != source_hash:
        raise ValueError("AI预标注来源与原表不一致")
    samples = prelabels.get("samples")
    preferred = (
        {r.get("sample_id") for r in samples if isinstance(r, dict) and r.get("agent_pass") == 0}
        if isinstance(samples, list)
        else set()
    )
    selected: dict[str, dict[str, str]] = {}
    for row in rows:
        key = row["case_id"]
        if key not in selected or (
            row["sample_id"] in preferred and selected[key]["sample_id"] not in preferred
        ):
            selected[key] = row
    references_path = source.parent / "hidden-reference.json"
    references = (
        object_map(
            object_map(json.loads(references_path.read_text(encoding="utf-8"))).get("references")
        )
        if references_path.exists()
        else {}
    )
    output = []
    mapping = {}
    for i, row in enumerate(selected.values(), 1):
        requirement, actions = task_and_actions(row["task"])
        identifier = f"{i:02d}"
        output.append(
            {
                "编号": identifier,
                "场景说明": scene(row["conditions"]),
                "你当时的要求": requirement,
                "你做过的操作": actions,
                "AI的最后回复": row["answer"],
                "名词解释": terms_explanation(row["answer"]),
            }
        )
        reference = object_map(references.get(row["sample_id"]))
        mapping[identifier] = {
            "sample_id": row["sample_id"],
            "case_id": row["case_id"],
            "model_reference": reference.get("model_reference"),
        }
    source_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / "标注表.csv"
    with target.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(output)
    metadata = {
        "source_sha256": source_hash,
        "source_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "provisional_sha256": hashlib.sha256(provisional.read_bytes()).hexdigest(),
        "source_manifest": source_manifest,
        "rows": len(output),
        "human_labels": "empty",
        "references_sha256": hashlib.sha256(references_path.read_bytes()).hexdigest()
        if references_path.exists()
        else None,
        "selection": "one per case; prefer AI-provisional failed sample; "
        "not representative quality rate",
    }
    artifacts = {
        "对照表.json": json.dumps({"references": mapping}, ensure_ascii=False, indent=2) + "\n",
        "怎么标.md": GUIDE,
        "manifest.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    }
    for name, text in artifacts.items():
        with (directory / name).open("x", encoding="utf-8") as handle:
            handle.write(text)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / ".cache/batch-2026-10-14/labeling")
    args = parser.parse_args()
    print(
        prepare_sheet(
            OLD / "human-labels.csv",
            OLD / "manifest.json",
            OLD / "agent-provisional.json",
            args.out,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

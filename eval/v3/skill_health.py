"""从已保存 v3 事件统计 Skill 的加载体检。"""

import argparse
import json
from pathlib import Path
from typing import NamedTuple, get_args

from backend.domain.external_data import ExternalAttempt
from backend.domain.tool_facts import SkillName
from backend.tools.contracts import ToolResult
from backend.tools.skill_config import SkillConfig
from backend.tools.travel import signalled_skills


class Trigger(NamedTuple):
    case_id: str
    expected: bool
    point: str


TRIGGERS: dict[SkillName, tuple[Trigger, ...]] = {
    "hotel-comparison": (
        Trigger("p2-commerce-1-01", True, "有含早餐报价，用户要求比较"),
        Trigger("p2-out-of-scope-1-01", False, "范围外请求，没有报价"),
        Trigger("p2-ambiguous-1-01", False, "日期未定，先澄清"),
    ),
    "itinerary-revision": (
        Trigger("p2-local-edit-1-01", True, "已有草稿，只换下午一个项目"),
        Trigger("p2-main-flow-1-02", False, "没有旧稿，第一次规划"),
        Trigger("p2-local-edit-1-02", True, "更改单日时段并保留其余项目"),
    ),
    "multi-city": (
        Trigger("p2-main-flow-1-01", True, "首段与次段均需选住宿"),
        Trigger("p2-main-flow-1-02", False, "单城市住宿"),
        Trigger("p2-main-flow-1-04", True, "一晚后转场的短住宿段"),
    ),
    "budget-relaxation": (
        Trigger("p2-fault-1-01", True, "供应商查无房，服务端返回住宿诊断"),
        Trigger("p2-memory-1-01", False, "没有查询住宿"),
        Trigger("p2-ambiguous-1-01", False, "入住日期未知，无有效报价可放宽"),
    ),
    "external-errors": (
        Trigger("p2-fault-2-01", True, "已观察到一次 HTTP 429 后恢复"),
        Trigger("p2-main-flow-1-02", False, "供应商正常返回，未重试"),
        Trigger("p2-fault-2-02", True, "带已知住宿条件的重试恢复"),
    ),
    "repair-limit": (
        Trigger("repair-cap-exhausted", True, "明确返回 repair_limit"),
        Trigger("p2-main-flow-1-02", False, "正常暂存，未到上限"),
        Trigger("repair-last-round-success", False, "最后一次允许的修复成功"),
    ),
}


class SignalFixture(NamedTuple):
    name: str
    result: ToolResult
    expected: bool
    description: str


SERVICE_FIXTURES: dict[SkillName, tuple[SignalFixture, ...]] = {
    "multi-city": (
        SignalFixture(
            "update_travel_request", ToolResult({}, segmented=True), True, "确认两个住宿段"
        ),
        SignalFixture("update_travel_request", ToolResult({}), False, "只更新单城"),
        SignalFixture("search_hotel_offers", ToolResult({}, segmented=True), True, "分段报价"),
    ),
    "budget-relaxation": (
        SignalFixture(
            "search_hotel_offers",
            ToolResult({"relaxation": {"tier": "1.5"}}),
            True,
            "实际进入放宽档位",
        ),
        SignalFixture(
            "search_hotel_offers",
            ToolResult({"relaxation": {"in_budget": 3, "steps": []}}),
            False,
            "正常报价",
        ),
        SignalFixture(
            "search_hotel_offers",
            ToolResult({"choice_card": "declined"}),
            True,
            "查看已拒绝的放宽结果",
        ),
    ),
    "external-errors": (
        SignalFixture(
            "search_places",
            ToolResult({}, code="timeout", external=ExternalAttempt(kind="timeout")),
            True,
            "查询超时",
        ),
        SignalFixture(
            "search_places", ToolResult({}, external=ExternalAttempt(attempts=1)), False, "一次成功"
        ),
        SignalFixture(
            "search_places",
            ToolResult({}, external=ExternalAttempt(attempts=2, recovered_from="timeout")),
            True,
            "重试后恢复",
        ),
    ),
    "repair-limit": (
        SignalFixture(
            "validate_itinerary",
            ToolResult({}, code="blocked", detail=("repair_limit",)),
            True,
            "已用完修复轮次",
        ),
        SignalFixture("stage_plan_change", ToolResult({}), False, "正常暂存"),
        SignalFixture(
            "validate_itinerary",
            ToolResult({"repair_rounds_remaining": 0}),
            False,
            "最后一轮修复成功",
        ),
    ),
}


def service_report() -> list[str]:
    lines = ["## 服务端信号夹具", "", "| Skill | 用例 | 实际路由符合预期 |", "| --- | --- | --- |"]
    for skill, examples in SERVICE_FIXTURES.items():
        for example in examples:
            emitted = skill in signalled_skills(example.name, example.result)
            matches = "是" if emitted == example.expected else "否"
            lines.append(f"| {skill} | {example.description} | {matches} |")
    return lines


def report(result: Path | None) -> str:
    rows = (
        [json.loads(line) for line in result.read_text(encoding="utf-8").splitlines() if line]
        if result
        else []
    )
    manifest = result.with_name("manifest.json") if result else None
    recorded = (
        json.loads(manifest.read_text(encoding="utf-8")).get("started_at", "")[:10]
        if manifest and manifest.is_file()
        else ""
    )
    lines = [
        "# Skill 触发体检",
        "",
        "| Skill | 触发召回 | 误加载率 | 字符数 | 最近评测 | 加载增益 |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for name in get_args(SkillName):
        loaded = {True: [0, 0], False: [0, 0]}
        for trigger in TRIGGERS[name]:
            for row in rows:
                if row["case_id"] != trigger.case_id or row.get("infra_error"):
                    continue
                detected = any(skill["name"] == name for skill in row.get("skills", []))
                loaded[trigger.expected][0] += detected
                loaded[trigger.expected][1] += 1
        recall = f"{loaded[True][0]}/{loaded[True][1]}" if loaded[True][1] else "待测"
        extra = f"{loaded[False][0]}/{loaded[False][1]}" if loaded[False][1] else "待测"
        chars = len(SkillConfig().path(name).read_text(encoding="utf-8"))
        last = recorded if recorded and (loaded[True][1] or loaded[False][1]) else "待测"
        lines.append(f"| {name} | {recall} | {extra} | {chars} | {last} | 待 E5 |")
    lines += ["", *service_report(), "", "## 用例预期", ""]
    for name, triggers in TRIGGERS.items():
        lines.append(f"### {name}\n")
        for trigger in triggers:
            expected = "加载" if trigger.expected else "不加载"
            lines.append(f"- `{trigger.case_id}` · {expected} · {trigger.point}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report(args.trials), encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""跑 SDK × 用例 × 重复次数，结果写到 results/<名字>.jsonl 与 <名字>-summary.md。

用法: uv run python -m bench.run [--sdk pydantic_ai pi ...] [--case E2a_native_output ...]
                                 [--repeat 3] [--name flash]
"""

import argparse
import asyncio
import importlib
import json
import statistics
import time
import traceback
import uuid
from pathlib import Path

from bench.common import MODEL, Case, NotSupported, RunCtx
from bench.proxy import Proxy, RunTraffic
from bench.tasks import CASES
from bench.tools import ToolEnv

# sdk名 -> (适配器模块, 额外参数)
ADAPTERS = {
    "pydantic_ai": ("pydantic_ai_agent", {}),
    "openai_agents": ("openai_agents", {}),
    "langchain": ("langchain_agent", {}),
    "claude_agent_sdk": ("claude_agent", {}),
    "pi": ("pi_agent", {}),
}
# 消融：只改一个变量验证因果，默认不跑，用 --sdk 显式指定
ABLATIONS = {"pydantic_ai+forced_tool": ("pydantic_ai_agent", {"force_tool": True})}
COLUMNS = ("SDK", "通过", "中位耗时s", "平均模型请求", "平均输入token", "平均输出token")
COLUMNS += ("平均成本¥", "工具并发峰值")
RESULTS = Path(__file__).resolve().parents[1] / "results"
PRICES_CNY_PER_M = {"deepseek-flash": (2, 8), "deepseek-v4-pro": (9, 27)}  # 同 backend/limits.py


async def one(proxy: Proxy, sdk: str, case: Case, grade, rep: int, sem: asyncio.Semaphore) -> dict:
    async with sem:
        run_id = uuid.uuid4().hex[:8]
        env = ToolEnv(fail_first=case.fail_first, latency=dict(case.latency))
        traffic = RunTraffic(*case.api_fault)
        proxy.register(run_id, traffic)
        ctx = RunCtx(env, proxy.base(run_id), proxy.base(run_id) + "/anthropic")
        name, kwargs = (ADAPTERS | ABLATIONS)[sdk]
        module = importlib.import_module(f"bench.adapters.{name}")
        row: dict = {
            "sdk": sdk,
            "case": case.id,
            "exp": case.experiment,
            "rep": rep,
            "model": MODEL,
        }
        start = time.perf_counter()
        try:
            out = await asyncio.wait_for(module.run(case, ctx, **kwargs), timeout=300)
            passed, reason = grade(env, out)
            row["text"], row["structured"] = out.text[-600:], out.structured
        except NotSupported as exc:
            passed, reason, row["unsupported"] = False, f"不支持: {exc}", True
        except Exception as exc:  # 框架抛错也是结果
            passed, reason = False, f"CRASH {type(exc).__name__}: {str(exc)[:240]}"
            row["trace"] = traceback.format_exc()[-1500:]
        ok = traffic.ok_requests
        row |= {
            "passed": passed,
            "reason": reason,
            "seconds": round(time.perf_counter() - start, 2),
            "model_requests": len(traffic.requests),
            "tokens_in": sum(r.get("tokens_in", 0) for r in ok),
            "tokens_out": sum(r.get("tokens_out", 0) for r in ok),
            "tool_calls": [c["name"] + ("" if c["ok"] else "!") for c in env.calls],
            "max_parallel_tools": env.max_active,
        }
        flag = "PASS" if passed else "FAIL"
        print(
            f"{sdk:16} {case.id:18} #{rep} {flag} {row['seconds']:6.1f}s {reason[:80]}", flush=True
        )
        return row


def _cell(rows: list[dict]) -> str:
    if not rows:
        return "—"
    if all(r.get("unsupported") for r in rows):
        return "不支持"
    return f"{sum(r['passed'] for r in rows)}/{len(rows)}"


def summarize(rows: list[dict]) -> str:
    model = rows[0]["model"]
    price_in, price_out = PRICES_CNY_PER_M.get(model, (0, 0))
    sdks = list(dict.fromkeys(r["sdk"] for r in rows))
    cases = list(dict.fromkeys(r["case"] for r in rows))
    head = ["SDK", *cases]
    lines = [
        f"## 通过次数（模型 {model}）",
        "",
        "| " + " | ".join(head) + " |",
        "|---" * len(head) + "|",
    ]
    for sdk in sdks:
        cells = [_cell([r for r in rows if r["sdk"] == sdk and r["case"] == c]) for c in cases]
        lines.append("| " + " | ".join([sdk, *cells]) + " |")
    for case in cases:
        lines += [
            "",
            f"## {case}",
            "",
            "| " + " | ".join(COLUMNS) + " |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for sdk in sdks:
            mine = [r for r in rows if r["sdk"] == sdk and r["case"] == case]
            ran = [r for r in mine if not r.get("unsupported")]
            if not mine:
                continue
            if not ran:
                lines.append(f"| {sdk} | 不支持 | | | | | | |")
                continue

            def avg(key: str, ran: list[dict] = ran) -> float:
                return statistics.mean(r[key] for r in ran)

            cost = (avg("tokens_in") * price_in + avg("tokens_out") * price_out) / 1e6
            values = [
                sdk,
                _cell(mine),
                f"{statistics.median(r['seconds'] for r in ran):.1f}",
                f"{avg('model_requests'):.1f}",
                f"{avg('tokens_in'):.0f}",
                f"{avg('tokens_out'):.0f}",
                f"{cost:.4f}",
                f"{max(r['max_parallel_tools'] for r in ran)}",
            ]
            lines.append("| " + " | ".join(values) + " |")
    fails = [r for r in rows if not r["passed"] and not r.get("unsupported")]
    if fails:
        lines += ["", "## 失败明细", ""]
        lines += [f"- {r['sdk']} {r['case']}#{r['rep']}: {r['reason']}" for r in fails]
    return "\n".join(lines)


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sdk", nargs="*", default=list(ADAPTERS))
    p.add_argument("--case", nargs="*", default=[c.id for c, _ in CASES])
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--name", default=time.strftime("%Y%m%d-%H%M%S"))
    args = p.parse_args()
    proxy, sem = Proxy(), asyncio.Semaphore(args.concurrency)
    jobs = [
        one(proxy, sdk, case, grade, rep, sem)
        for sdk in args.sdk
        for case, grade in CASES
        if case.id in args.case
        for rep in range(args.repeat)
    ]
    rows = await asyncio.gather(*jobs)
    RESULTS.mkdir(exist_ok=True)
    lines = (json.dumps(r, ensure_ascii=False) for r in rows)
    (RESULTS / f"{args.name}.jsonl").write_text("\n".join(lines), encoding="utf-8")
    summary = summarize(rows)
    (RESULTS / f"{args.name}-summary.md").write_text(summary + "\n", encoding="utf-8")
    print("\n" + summary)


if __name__ == "__main__":
    asyncio.run(main())

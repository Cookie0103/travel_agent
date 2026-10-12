"""数据库工具的真实SDK离线测试共用启动器；私有连接串只交给自有worker stdin。"""

import json
import os
from decimal import Decimal
from pathlib import Path

from backend.domain.execution import RunContext
from backend.limits import Settings
from backend.mcp.bridge import sdk_tool_name
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import find_cli, worker_environment
from backend.providers.claude_agent.evaluation import EvaluationVariant, evaluation_definitions
from backend.providers.claude_agent.guard import Forward, Guard, serve
from backend.providers.claude_agent.process import invoke_worker, run_process
from backend.services.travel import TravelService
from backend.tools.workflow import WorkflowName


class CompactionHistory:
    """只有本地替身建立已完成历史，业务工具后才抬高usage触发原生压缩。"""

    def __init__(self, forward: Forward, *, summary_failure: bool = False) -> None:
        self.forward = forward
        self.summary_failure = summary_failure
        self.requests: list[dict[str, object]] = []
        self.warmups: list[dict[str, object]] = []
        self.business: list[dict[str, object]] = []
        self.summaries: list[dict[str, object]] = []
        self.event_path: Path | None = None

    def __call__(self, body: bytes) -> tuple[int, bytes]:
        from tests.test_sdk_cli_offline import scripted_response

        request = json.loads(body)
        self.requests.append(request)
        latest = next(m["content"] for m in reversed(request["messages"]) if m["role"] == "user")
        summary = "REMINDER: Do NOT call any tools." in str(latest) and "<summary>" in str(latest)
        if summary:
            self.summaries.append(request)
            assert len(self.warmups) == 2 and self.business, "summary must follow business request"
            assert self.event_path is not None
            events = [json.loads(line) for line in self.event_path.read_text().splitlines()]
            assert any(
                event.get("kind") == "tool_finished"
                and event.get("tool_name") == "load_skill"
                and event.get("code") is None
                for event in events
            ), "summary requires prior successful business tool"
            if self.summary_failure:
                return (
                    503,
                    b'{"error":{"type":"api_error","message":"fixture-summary-unavailable"}}',
                )
            status, response = scripted_response(
                b'{"messages":[{"content":[{"type":"tool_result",'
                b'"content":"Synthetic summary."}]}]}'
            )
        elif "offline-history-warmup-" in str(latest):
            self.warmups.append(request)
            status, response = scripted_response(
                json.dumps(
                    {
                        "messages": [
                            {
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "content": "Synthetic assistant context. " * 400,
                                    }
                                ]
                            }
                        ]
                    }
                ).encode()
            )
            tokens = 8000 if len(self.warmups) == 1 else 11000
            assert tokens + 2000 < len(body) * 5 // 4 + 1024
            response = response.replace(
                b'"input_tokens": 100', f'"input_tokens": {tokens}'.encode()
            )
            response = response.replace(b'"output_tokens": 20', b'"output_tokens": 2000')
        else:
            self.business.append(request)
            status, response = self.forward(body)
            if len(self.business) == 1:
                # 同控制组的人工usage；低于字节预占，非真实token/摘要质量。
                assert 22000 + 2000 < len(body) * 5 // 4 + 1024
                response = response.replace(b'"input_tokens": 100', b'"input_tokens": 22000')
        return status, response.replace(
            b'"msg_offline"', f'"msg_offline_{len(self.requests)}"'.encode()
        )


def run_database_worker(
    travel: TravelService,
    context: RunContext,
    directory: Path,
    forward: Forward,
    prompt: str,
    *,
    max_attempts: int = 4,
    supplier_url: str | None = None,
    auto_compact_percent: int | None = None,
    prompts: list[str] | None = None,
    workflow: WorkflowName | None = None,
    variant: EvaluationVariant = "full",
) -> tuple[dict[str, object], Guard]:
    guard = Guard(
        Settings("offline-only", "deepseek-flash", Decimal(5), Decimal(0)),
        Budget(directory / "ledger", directory / "old", Decimal(5)),
        forward,
        allowed_tools=frozenset(
            sdk_tool_name(d.name) for d in evaluation_definitions(variant, database=True)
        ),
        max_attempts=max_attempts,
    )
    with serve(guard) as endpoint:
        cli = find_cli(os.environ)
        worker = directory / "worker"
        if isinstance(forward, CompactionHistory):
            forward.event_path = worker / f"events-{context.run_id}.jsonl"
        env = worker_environment(
            os.environ,
            worker,
            Path(__file__).resolve().parents[2],
            endpoint,
            guard.token,
            "deepseek-flash",
        )
        if auto_compact_percent is not None:
            env["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] = str(auto_compact_percent)
            env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "100000"
            env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = "200000"
        version = run_process([str(cli), "--version"], worker, env, timeout=10)
        report = invoke_worker(
            cli,
            worker,
            env,
            module="tests.integration.sdk_context_worker"
            if auto_compact_percent is not None
            else "backend.providers.claude_agent.worker",
            payload={
                "prompts": prompts if prompts is not None else [prompt],
                "user_id": str(context.user_id),
                "session_id": str(context.session_id),
                "run_id": str(context.run_id),
                "cli_version": version.stdout.split()[0],
                "database_dsn": travel.database.engine.url.render_as_string(hide_password=False),
                "supplier_url": supplier_url,
                "workflow": workflow,
                "evaluation_variant": variant,
            },
        )
    return report, guard

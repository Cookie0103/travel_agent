"""pi（TypeScript）：node子进程跑Agent，工具经本地HTTP回调同一份Python实现。pi没有原生结构化输出。"""

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bench.common import (
    API_KEY,
    MAX_MODEL_CALLS,
    MODEL,
    SYSTEM_PROMPT,
    Case,
    NotSupported,
    RunCtx,
    RunOutput,
)
from bench.tools import Tool, ToolError, json_schema, make_tools, tool_doc

SCRIPT = Path(__file__).resolve().parents[2] / "pi" / "run.mjs"


def _serve(tools: dict[str, Tool], loop: asyncio.AbstractEventLoop) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            future = asyncio.run_coroutine_threadsafe(tools[req["name"]](**req["args"]), loop)
            try:
                body = {"ok": True, "text": future.result()}
            except ToolError as exc:
                body = {"ok": False, "error": str(exc)}
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def run(case: Case, ctx: RunCtx) -> RunOutput:
    if case.output:
        raise NotSupported("pi-agent-core 没有原生结构化输出")
    tools = make_tools(ctx.env, case.tools)
    server = _serve({fn.__name__: fn for fn in tools}, asyncio.get_running_loop())
    payload = {
        "prompt": case.prompt,
        "baseUrl": ctx.openai_base,
        "model": MODEL,
        "systemPrompt": SYSTEM_PROMPT,
        "maxSteps": MAX_MODEL_CALLS,
        "toolUrl": f"http://127.0.0.1:{server.server_port}",
        "tools": [
            {"name": fn.__name__, "description": tool_doc(fn), "parameters": json_schema(fn)}
            for fn in tools
        ],
    }
    try:
        proc = await asyncio.create_subprocess_exec(
            "node",
            str(SCRIPT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "DEEPSEEK_API_KEY": API_KEY},
        )
        stdout, stderr = await proc.communicate(json.dumps(payload, ensure_ascii=False).encode())
    finally:
        server.shutdown()
    if proc.returncode:
        lines = stderr.decode(errors="replace").strip().splitlines()
        errors = [line for line in lines if "Error" in line]
        raise RuntimeError((errors or lines or ["node failed"])[0][:300])
    return RunOutput(text=json.loads(stdout)["text"])

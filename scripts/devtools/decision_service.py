"""本机运行固定版本的 Intern-Decision 文本体检。"""

import argparse
import importlib.util
import json
import sys
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


def peak_rss_bytes() -> int | None:
    if sys.platform != "win32":
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return usage if sys.platform == "darwin" else usage * 1024
    return None


def handler(predict: Callable[[dict[str, Any]], dict[str, Any]]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def write_response(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/health":
                self.write_response(404, {})
                return
            self.write_response(200, {"max_rss_bytes": peak_rss_bytes()})

        def do_POST(self) -> None:
            if self.path != "/v1/systemone":
                self.write_response(404, {})
                return
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 24576:
                    raise ValueError("bad request size")
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict) or set(request) != {"state", "questions"}:
                    raise ValueError("text-only request expected")
            except (ValueError, TypeError, OSError):
                self.write_response(400, {})
                return
            try:
                self.write_response(200, predict(request))
            except Exception as error:
                print(f"decision_failed {type(error).__name__}", flush=True)
                self.write_response(503, {})

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--port", type=int, default=8124)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    parser.add_argument("--show-memory", action="store_true")
    args = parser.parse_args()
    checkpoint = args.checkpoint.resolve()
    spec = importlib.util.spec_from_file_location(
        "intern_decision_inference", checkpoint / "inference.py"
    )
    if spec is None or spec.loader is None:
        parser.error("checkpoint 缺少官方 inference.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    engine = module.DecisionEngine(
        checkpoint, device=args.device, attn_implementation="eager", max_length=2048
    )
    if args.show_memory:
        memory = {"max_rss_bytes": peak_rss_bytes()}
        if args.device == "mps":
            mps = module.torch.mps
            mps.synchronize()
            memory["mps_model_bytes"] = mps.current_allocated_memory()
            memory["mps_driver_bytes"] = mps.driver_allocated_memory()
        print(json.dumps(memory), flush=True)
        return 0
    with HTTPServer(("127.0.0.1", args.port), handler(engine.predict)) as service:
        print(f"ready 127.0.0.1:{args.port} device={args.device}", flush=True)
        service.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

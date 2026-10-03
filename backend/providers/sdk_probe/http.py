"""固定 DeepSeek HTTPS 传输；复用进程总期限覆盖 DNS、连接和慢流。"""

import http.client
import json
import os
import subprocess
import sys
from pathlib import Path

from backend.providers.probe.settings import ProbeError
from backend.providers.sdk_probe.process import run_process

MAX_RESPONSE_BYTES = 1_048_576


def forward_deepseek(api_key: str, body: bytes) -> tuple[int, bytes]:
    """整个 DNS/连接/读取在可回收进程中限时，真实 key 仅通过 stdin 传递。"""
    root = Path(__file__).resolve().parents[3]
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    }
    env.update(PYTHONPATH=str(root), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        result = run_process(
            [sys.executable, "-m", "backend.providers.sdk_probe.http"],
            root,
            env,
            50,
            json.dumps({"key": api_key, "body": body.decode("utf-8")}),
        )
    except subprocess.TimeoutExpired:
        raise ProbeError("timeout", "DeepSeek 请求总期限已到，保留预占") from None
    if result.returncode != 0:
        raise ProbeError("unavailable", "DeepSeek 请求工作进程失败")
    try:
        raw = json.loads(result.stdout)
        if raw.get("status") != "ok" or type(raw.get("http_status")) is not int:
            raise ValueError
        content = raw["content"]
        if not isinstance(content, str):
            raise ValueError
        return raw["http_status"], content.encode("utf-8")
    except (ValueError, AttributeError, KeyError, TypeError):
        raise ProbeError("unavailable", "DeepSeek 请求失败或返回格式无效") from None


def _direct_request(api_key: str, body: bytes) -> tuple[int, bytes]:
    """不使用代理环境、不跟随重定向；一次 reserve 对应一次 HTTP 尝试。"""
    connection = http.client.HTTPSConnection("api.deepseek.com", timeout=45)
    try:
        connection.request(
            "POST",
            "/anthropic/v1/messages",
            body,
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
        )
        response = connection.getresponse()
        content = response.read(MAX_RESPONSE_BYTES + 1)
        if len(content) > MAX_RESPONSE_BYTES:
            raise ProbeError("provider_error", "上游响应超过实验上限")
        return response.status, content
    finally:
        connection.close()


def main() -> None:
    """私有传输进程：错误只回固定分类，不打印密钥或 HTTP 异常正文。"""
    try:
        request = json.loads(sys.stdin.read())
        status, content = _direct_request(request["key"], request["body"].encode("utf-8"))
        response: dict[str, object] = {
            "status": "ok",
            "http_status": status,
            "content": content.decode("utf-8"),
        }
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException, ProbeError):
        response = {"status": "error"}
    print(json.dumps(response))


if __name__ == "__main__":
    main()

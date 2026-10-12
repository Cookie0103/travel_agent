"""获取固定 commit 的只读上游：M0.1 阅读准备，不安装或执行上游代码。"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Upstream:
    """来自 06 来源记录的固定版本与是否必需。"""

    name: str
    url: str
    commit: str
    required: bool


UPSTREAMS = (
    Upstream(
        "commerce-agents",
        "https://github.com/anthropics/commerce-agents.git",
        "fd4d59224ab96b43c6dc6888207c67b3bd5a24cf",
        True,
    ),
    Upstream(
        "datamind-ai-agent",
        "https://github.com/plaidev/datamind-ai-agent.git",
        "d57bb79e3cb16377fa2f6587f110f79ccd5141e1",
        False,
    ),
)


class FetchError(RuntimeError):
    """获取或版本检查失败；诊断文本不包含凭据与上游文件内容。"""


def git(*args: str, timeout: int = 180) -> str:
    """禁止交互式登录，给网络操作上限，避免无人值守卡住。"""
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    try:
        result = subprocess.run(
            ["git", "-c", "credential.interactive=false", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except OSError as exc:
        raise FetchError("unavailable: 无法启动 Git 或访问路径。") from exc
    except subprocess.TimeoutExpired as exc:
        raise FetchError("timeout: Git 操作超时；保留现场供下次核对。") from exc
    if result.returncode:
        # Git 错误可能含凭据相关 URL；只报告阶段与退出码，不回显原始 stderr。
        raise FetchError(f"unavailable: Git 操作失败（退出码 {result.returncode}）。")
    return result.stdout.strip()


def fetch(upstream: Upstream, vendor: Path) -> None:
    """已有目录只核对、不修改；新目录拉取后切换到指定 commit。"""
    destination = vendor / upstream.name
    if destination.exists():
        if not (destination / ".git").exists():
            raise FetchError(f"conflict: {upstream.name} 已存在但不是 Git 仓库，请人工检查。")
        actual = git("-C", str(destination), "rev-parse", "HEAD", timeout=15)
        if actual != upstream.commit:
            raise FetchError(f"conflict: {upstream.name} 版本不符，保留原目录，不自动重置。")
        print(f"skip: {upstream.name} 已固定到 {actual}")
        return
    vendor.mkdir(parents=True, exist_ok=True)
    git("clone", "--filter=blob:none", "--no-checkout", upstream.url, str(destination))
    git("-C", str(destination), "checkout", "--detach", upstream.commit)
    actual = git("-C", str(destination), "rev-parse", "HEAD", timeout=15)
    if actual != upstream.commit:
        raise FetchError(f"conflict: {upstream.name} checkout 后版本不符。")
    print(f"ready: {upstream.name} {actual}")


def main() -> int:
    """Commerce 是必需输入；DataMind 不可访问只告警。"""
    for upstream in UPSTREAMS:
        try:
            fetch(upstream, ROOT / "vendor")
        except FetchError as exc:
            if upstream.required:
                print(f"error: {upstream.name}: {exc}", file=sys.stderr)
                return 1
            print(f"warning: {upstream.name}: {exc} M0.1 继续；M0.6 前再处理。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

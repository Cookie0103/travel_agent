"""创建 SDK 工作进程的最小环境，避免继承本机 Claude 登录和其他供应商。"""

import os
import shutil
from collections.abc import Mapping
from pathlib import Path

from backend.providers.claude_agent.limits import ProbeError
from backend.providers.claude_agent.profile import current


def find_cli(environment: Mapping[str, str]) -> Path:
    """明确选定可执行文件；不执行 npm/cmd 包装器。"""
    configured = environment.get("TRAVEL_CLAUDE_CLI")
    located = configured or shutil.which("claude")
    if not located or not Path(located).is_file():
        raise ProbeError("unavailable", "未找到 Claude CLI；配置 TRAVEL_CLAUDE_CLI")
    path = Path(located).resolve()
    if os.name == "nt" and path.suffix.lower() != ".exe":
        raise ProbeError("validation", "Windows 需要原生 Claude exe")
    return path


def worker_environment(
    source: Mapping[str, str], directory: Path, root: Path, endpoint: str, token: str, model: str
) -> dict[str, str]:
    """白名单启动新进程，不通过修改父进程 os.environ 影响其他用户任务。"""
    names = {
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATH",
        "PATHEXT",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "GOOGLE_MAPS_API_KEY",
        "RAKUTEN_APP_ID",
        "RAKUTEN_ACCESS_KEY",
        "RAKUTEN_AFFILIATE_ID",
        "RAKUTEN_REFERER",
        "GOOGLE_GEOCODE_DAILY_CAP",
        "GOOGLE_PLACES_DAILY_CAP",
        "GOOGLE_ROUTES_DAILY_CAP",
        "RAKUTEN_DAILY_CAP",
        "WEATHER_DAILY_CAP",
        "TRAVEL_PROFILE",
    }
    env = {k: v for k, v in source.items() if k.upper() in names}
    if os.name == "nt":
        bash = find_git_bash(source)
        if bash:
            env["CLAUDE_CODE_GIT_BASH_PATH"] = str(bash)
    home = directory / "home"
    config = directory / "config"
    home.mkdir(parents=True, exist_ok=True)
    config.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(home),
            "LOCALAPPDATA": str(home),
            "CLAUDE_CONFIG_DIR": str(config),
            "PYTHONPATH": str(root),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "ANTHROPIC_BASE_URL": endpoint,
            "ANTHROPIC_AUTH_TOKEN": token,
            "ANTHROPIC_MODEL": model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
            "ANTHROPIC_SMALL_FAST_MODEL": model,
            "CLAUDE_CODE_MAX_RETRIES": "0",
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(current(source).max_output),
            "MAX_THINKING_TOKENS": "0",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_AUTOUPDATER": "1",
            "DISABLE_TELEMETRY": "1",
            "DISABLE_ERROR_REPORTING": "1",
            "ENABLE_TOOL_SEARCH": "false",
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "CLAUDE_CODE_DISABLE_1M_CONTEXT": "1",
            "API_TIMEOUT_MS": str(int((current(source).upstream_timeout + 10) * 1000)),
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    return env


def find_git_bash(source: Mapping[str, str]) -> Path | None:
    """Git 钩子会改变 PATH；从 Git 安装根定位 bash，避免误选 Windows WSL 启动器。"""
    configured = source.get("CLAUDE_CODE_GIT_BASH_PATH")
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise ProbeError("unavailable", "配置的 Git Bash 不存在")
        return path.resolve()
    path_value = next((v for k, v in source.items() if k.upper() == "PATH"), "")
    git = shutil.which("git", path=path_value)
    if git:
        for parent in Path(git).resolve().parents:
            candidate = parent / "bin" / "bash.exe"
            if candidate.is_file():
                return candidate
    return None

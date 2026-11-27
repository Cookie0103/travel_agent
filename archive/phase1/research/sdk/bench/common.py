"""实验共享的配置与类型。所有SDK用同一个DeepSeek模型（关闭思考）、同一套工具、同一个步数预算。"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

from bench.tools import ToolEnv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

API_KEY = os.environ["DEEPSEEK_API_KEY"]
MODEL = os.environ.get("BENCH_MODEL") or os.environ.get("DEEPSEEK_MODEL") or "deepseek-flash"
NO_THINKING = {"thinking": {"type": "disabled"}}
MAX_MODEL_CALLS = 20  # 统一的资源预算（不是行为差异），各SDK换算成自己的参数
SYSTEM_PROMPT = (
    "你是京都旅行助手。今天是2026-11-04。只根据工具返回的数据回答，"
    "不要自己估算价格或时间。回答用中文。"
)


class NotSupported(Exception):
    """该SDK没有对应的原生机制。"""


@dataclass(frozen=True)
class Case:
    id: str
    experiment: str
    prompt: str
    tools: tuple[str, ...]
    output: type[BaseModel] | None = None  # 需要SDK原生结构化输出时的目标类型
    fail_first: frozenset[str] = frozenset()  # 第一次调用即失败的工具
    latency: dict[str, float] = field(default_factory=dict)  # 工具人为延迟（秒）
    api_fault: tuple[int, int] = (0, 0)  # (状态码, 前N个模型请求失败)


@dataclass
class RunCtx:
    env: ToolEnv
    openai_base: str  # 经过计量代理的 OpenAI 兼容地址
    anthropic_base: str  # 经过计量代理的 Anthropic 兼容地址


@dataclass
class RunOutput:
    text: str = ""
    structured: dict | None = None

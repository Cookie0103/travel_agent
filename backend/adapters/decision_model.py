"""只连接回环的 System One 客户端，供离线评测补算。"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

import httpx
from pydantic import JsonValue


@dataclass(frozen=True)
class Signal:
    id: str
    question: str
    yes: str
    no: str


@dataclass(frozen=True)
class Decision:
    model: str
    revision: str
    forward: dict[str, float]
    reversed: dict[str, float]

    @property
    def yes(self) -> dict[str, float]:
        return {
            key: (probability + self.reversed[key]) / 2 for key, probability in self.forward.items()
        }


class DecisionClient:
    def __init__(
        self,
        endpoint: str,
        model: str,
        revision: str,
        cache: Path,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.port is None
            or parsed.path not in {"", "/"}
            or parsed.username is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("决策服务须使用明确端口的本机回环地址")
        if not model or not revision:
            raise ValueError("决策服务须登记模型和权重版本")
        self.endpoint = endpoint.rstrip("/") + "/v1/systemone"
        self.model = model
        self.revision = revision
        self.cache = cache
        self.transport = transport

    async def score(
        self, state: Mapping[str, JsonValue], signals: tuple[Signal, ...]
    ) -> Decision | None:
        if not 1 <= len(signals) <= 16 or len(signals) != len({item.id for item in signals}):
            raise ValueError("决策问题数须在 1–16 且标识唯一")
        forward = await self._ordered(state, signals, ("yes", "no"))
        if forward is None:
            return None
        reverse = await self._ordered(state, signals, ("no", "yes"))
        return (
            Decision(self.model, self.revision, forward, reverse) if reverse is not None else None
        )

    async def _ordered(
        self, state: Mapping[str, JsonValue], signals: tuple[Signal, ...], order: tuple[str, str]
    ) -> dict[str, float] | None:
        questions = {
            item.id: {
                "type": "choice",
                "instructions": item.question,
                "criteria": {key: item.yes if key == "yes" else item.no for key in order},
            }
            for item in signals
        }
        payload = {
            "state": json.dumps(dict(state), ensure_ascii=False, sort_keys=True, allow_nan=False),
            "questions": questions,
        }
        trace = {"model": self.model, "revision": self.revision, "order": order, "request": payload}
        data = json.dumps(trace, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(data.encode()) > 20_480:
            raise ValueError("决策输入过大，应先裁剪为该问题需要的事实")
        path = self.cache / (hashlib.sha256(data.encode()).hexdigest() + ".json")
        if path.is_file():
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
                cached = _read_answers(stored["response"], self.model, questions)
                if cached is not None:
                    return cached
            except (ValueError, KeyError, TypeError):
                pass
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False, trust_env=False, transport=self.transport
        ) as http:
            try:
                result = await http.post(self.endpoint, json=payload)
                result.raise_for_status()
                response = result.json()
            except (httpx.HTTPError, ValueError):
                return None
        probabilities = _read_answers(response, self.model, questions)
        if probabilities is None:
            return None
        self.cache.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.cache, delete=False
        ) as temporary:
            temporary.write(json.dumps({**trace, "response": response}, ensure_ascii=False) + "\n")
        Path(temporary.name).replace(path)
        return probabilities


def _read_answers(
    payload: object, model: str, questions: Mapping[str, object]
) -> dict[str, float] | None:
    if not isinstance(payload, dict) or payload.get("model") != model:
        return None
    answers = payload.get("answers")
    if not isinstance(answers, dict) or answers.keys() != questions.keys():
        return None
    result = {}
    for key, answer in answers.items():
        if not isinstance(answer, dict) or answer.get("type") != "choice":
            return None
        options = answer.get("probabilities")
        if not isinstance(options, dict) or options.keys() != {"yes", "no"}:
            return None
        yes, no = options["yes"], options["no"]
        if (
            type(yes) not in {float, int}
            or type(no) not in {float, int}
            or not (0 <= yes <= 1 and 0 <= no <= 1)
            or abs(yes + no - 1) > 0.01
        ):
            return None
        result[key] = float(yes)
    return result

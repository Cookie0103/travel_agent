import asyncio
import json
from pathlib import Path

import httpx

from backend.adapters.decision_model import DecisionClient
from eval.commerce.soft import SIGNALS, score_saved


def test_local_decision_averages_option_order_caches_and_degrades(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []
    signal = SIGNALS[0]

    def endpoint(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        order = tuple(body["questions"][signal.id]["criteria"])
        calls.append(order)
        yes = 0.8 if order == ("yes", "no") else 0.6
        return httpx.Response(
            200,
            json={
                "model": "fixture",
                "answers": {
                    signal.id: {"type": "choice", "probabilities": {"yes": yes, "no": 1 - yes}}
                },
            },
        )

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("离线", request=request)

    async def exercise() -> None:
        state = {"facts": "午间已留时间供儿童休息"}
        approved = frozenset({signal.id})
        client = DecisionClient(
            "http://127.0.0.1:8123",
            "fixture",
            "v1",
            tmp_path,
            transport=httpx.MockTransport(endpoint),
        )
        expected = {signal.id: 0.7}
        assert await score_saved(state, approved, client, rule_passed=True) == expected
        assert await score_saved(state, approved, client, rule_passed=True) == expected
        assert calls == [("yes", "no"), ("no", "yes")]
        assert await score_saved(state, approved, client, rule_passed=False) == {}
        offline = DecisionClient(
            "http://127.0.0.1:8123",
            "fixture",
            "v2",
            tmp_path,
            transport=httpx.MockTransport(unavailable),
        )
        assert await score_saved(state, approved, offline, rule_passed=True) == {}

    asyncio.run(exercise())

"""用户可见文本：不含围栏标签，不含英文内部字段名。"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.domain.itinerary import RouteInput
from backend.services.common import ServiceError
from backend.services.planning import PlanningService
from backend.tools.fencing import LABEL, fence, unfence


def test_unfence_unwraps_own_fence_only() -> None:
    text = f"目的地={fence('京都')}；段={fence('大阪')} 1—2"
    out = unfence(text)
    assert LABEL not in out
    assert out == "目的地=京都；段=大阪 1—2"
    assert unfence("普通文本") == "普通文本"


def test_unfence_removes_stray_tags() -> None:
    assert unfence(f"a<{LABEL}>b") == "ab"
    assert unfence(f"a</{LABEL}>b") == "ab"


def test_model_facing_fence_is_unchanged() -> None:
    assert fence("京都") == f"<{LABEL}>京都</{LABEL}>"


def test_route_missing_transport_message_is_chinese() -> None:
    travel = SimpleNamespace(
        read_request=lambda ctx: _request(),
    )
    service = PlanningService(travel)  # type: ignore[arg-type]
    arguments = RouteInput.model_validate(
        {
            "expected_revision": 1,
            "legs": [
                {
                    "from_evidence_id": str(uuid4()),
                    "to_evidence_id": str(uuid4()),
                    "departure": "2026-11-01T09:00+09:00",
                }
            ],
        }
    )
    with pytest.raises(ServiceError) as caught:
        asyncio.run(service.routes(None, arguments))  # type: ignore[arg-type]
    message = str(caught.value)
    assert "missing_fields" not in message and "transport" not in message
    assert "交通" in message
    assert caught.value.reason == "route_missing_transport"


async def _request() -> SimpleNamespace:
    return SimpleNamespace(revision=1, transport=None)

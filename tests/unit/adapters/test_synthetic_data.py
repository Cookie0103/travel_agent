"""F3：来源由构造边界指定，生产环境变量不能伪装成评测来源。"""

import asyncio
from typing import cast
from uuid import uuid4

from backend.adapters.evaluation_faults import evaluation_data
from backend.adapters.google_maps import _GooglePlace, place_from_response
from backend.adapters.live_data import LiveData
from backend.persistence.database import Database


def test_production_and_explicit_eval_factories_keep_distinct_source_modes() -> None:
    database = cast(Database, object())
    production = LiveData.from_environment(
        {"GOOGLE_MAPS_API_KEY": "synthetic", "DATA_MODE": "synthetic", "TRAVEL_PROFILE": "eval"},
        database,
    )
    evaluation = evaluation_data(
        "coverage", database, "postgresql://localhost/travel_agent_eval_" + uuid4().hex
    )
    try:
        assert production.data_mode == "live"
        assert production.google and production.google.data_mode == "live"
        assert evaluation.data_mode == "synthetic"
        assert evaluation.google and evaluation.google.data_mode == "synthetic"
        assert evaluation.rakuten and evaluation.rakuten.data_mode == "synthetic"
        assert evaluation.usage.daily["places"] == 60
        assert production.usage.daily["places"] == 25
    finally:
        asyncio.run(production.close())
        asyncio.run(evaluation.close())


def test_synthetic_place_carries_synthetic_source_attribution() -> None:
    place = _GooglePlace.model_validate(
        {
            "id": "synthetic-place-1",
            "displayName": {"text": "合成景点1"},
            "location": {"latitude": 35, "longitude": 135},
            "types": ["museum"],
        }
    )
    synthetic = place_from_response(place, "京都", data_mode="synthetic")
    real = place_from_response(place, "京都")
    assert (
        synthetic.source.data_mode == "synthetic" and synthetic.source.attribution == "合成评测数据"
    )
    assert real.source.data_mode == "live" and real.source.attribution == "Google Maps"

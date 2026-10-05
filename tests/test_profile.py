"""限额档位：次数/预算保持原值，联网、SDK与整轮期限有序。"""

from pathlib import Path
from typing import Any, cast

from backend.adapters.external_api import ApiUsage
from backend.providers.claude_agent.environment import worker_environment
from backend.providers.claude_agent.profile import DEFAULT, RELAXED, current


def test_default_keeps_call_caps_with_bounded_planning_deadlines() -> None:
    assert current({}) is DEFAULT and current({"TRAVEL_PROFILE": "other"}) is DEFAULT
    assert (DEFAULT.max_calls, DEFAULT.max_turns, DEFAULT.max_attempts) == (16, 12, 12)
    assert (DEFAULT.worker_timeout, DEFAULT.process_timeout, DEFAULT.run_timeout) == (210, 220, 240)
    assert DEFAULT.max_output == 2048
    assert dict(DEFAULT.run_caps) == {
        "geocode": 2, "places": 3, "routes": 12, "rakuten": 8, "weather": 1,
    }  # fmt: skip
    assert dict(DEFAULT.daily_defaults) == {
        "geocode": 50, "places": 25, "routes": 150, "rakuten": 150, "weather": 200,
    }  # fmt: skip


def test_relaxed_is_larger_and_timeouts_stay_ordered(tmp_path: Path) -> None:
    limits = current({"TRAVEL_PROFILE": "relaxed"})
    assert limits is RELAXED
    assert limits.max_calls == 40 and limits.max_turns == 30 and limits.max_attempts == 30
    assert limits.worker_timeout < limits.process_timeout < limits.run_timeout
    assert DEFAULT.worker_timeout < DEFAULT.process_timeout < DEFAULT.run_timeout
    for profile in (DEFAULT, RELAXED):
        env = worker_environment(
            {"TRAVEL_PROFILE": "relaxed"} if profile is RELAXED else {},
            tmp_path,
            Path.cwd(),
            "http://127.0.0.1:1",
            "synthetic",
            "deepseek-flash",
        )
        assert profile.upstream_timeout < int(env["API_TIMEOUT_MS"]) / 1000 < profile.worker_timeout
    for api, value in DEFAULT.run_caps.items():
        assert RELAXED.run_caps[api] > value and RELAXED.daily_defaults[api] > 0


def test_external_caps_follow_profile_and_explicit_env_wins() -> None:
    database = cast(Any, None)
    assert ApiUsage(database, {}).run_caps["routes"] == 12
    relaxed = ApiUsage(database, {"TRAVEL_PROFILE": "relaxed", "GOOGLE_ROUTES_DAILY_CAP": "7"})
    assert relaxed.run_caps["routes"] == 40
    assert relaxed.daily["routes"] == 7 and relaxed.daily["places"] == 150


def test_worker_environment_forwards_profile(tmp_path: Path) -> None:
    def build(source: dict[str, str]) -> dict[str, str]:
        return worker_environment(source, tmp_path, tmp_path, "http://x", "t", "m")

    env = build({"TRAVEL_PROFILE": "relaxed"})
    assert env["TRAVEL_PROFILE"] == "relaxed" and env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "4096"
    default = build({})
    assert "TRAVEL_PROFILE" not in default and default["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "2048"

"""SDK无工具路径的角色闭集与模拟用户结构。"""

from pathlib import Path

import pytest

from backend.agent.persona import evaluation_judge_prompt


def test_simulator_and_triage_have_separate_fixed_rubrics() -> None:
    assert "隐藏目标" in evaluation_judge_prompt("simulator")
    assert "first_step" in evaluation_judge_prompt("triage")


def test_simulator_cannot_combine_click_and_session_change() -> None:
    from eval.simulator import UserAction

    with pytest.raises(ValueError):
        UserAction.model_validate({"kind": "new_session", "text": "继续", "choice_id": "bad"})


def test_trial_runtime_rejects_non_evaluation_database(tmp_path: Path) -> None:
    from backend.providers.claude_agent.application import GuardedRuntime

    with pytest.raises(ValueError):
        GuardedRuntime(
            tmp_path, "postgresql+psycopg://localhost/travel_agent", evaluation_fault="429-ok"
        )


def test_user_scenarios_are_eight_and_default_cli_does_not_call_models() -> None:
    from unittest.mock import patch

    from eval.simulator import SCENARIOS
    from scripts import dev

    assert len(SCENARIOS) == 8 and len({s.case_id for s in SCENARIOS}) == 8
    with patch("scripts.dev.run_command", return_value=0) as run:
        assert dev.main(["eval-simulator", "--trace-cloud"]) == 2
        run.assert_not_called()
        assert dev.main(["eval-simulator"]) == 0
        assert "--live" not in run.call_args.args[0]


def test_recall_does_not_accept_denial_or_mixed_trip_leak() -> None:
    from eval.simulator import recalled

    assert not recalled("你没说喜欢特种兵，我不知道你的偏好。", long_term=True)
    assert not recalled("你不喜欢特种兵式旅行。", long_term=True)
    assert not recalled("没有长期资料，但你通常独自出行。", long_term=False)
    assert recalled("你已确认喜欢特种兵式旅行。", long_term=True)
    assert recalled("我不知道你的长期同行偏好。", long_term=False)

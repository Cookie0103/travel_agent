"""E6门禁：默认仅准备，真实抽样须显式live，cloud不能单独开启。"""

from unittest.mock import patch

from scripts import dev


def test_memory_evaluation_is_prepared_offline_and_explicit_live_is_one_repeat() -> None:
    with patch("scripts.dev.run_command", return_value=0) as run:
        assert dev.main(["eval-memory"]) == 0
        run.assert_not_called()
        assert dev.main(["eval-memory", "--trace-cloud"]) == 2
        run.assert_not_called()
        assert dev.main(["eval-memory", "--live", "--trace-cloud"]) == 0
        command = run.call_args.args[0]
        assert command[command.index("--suite") + 1] == "v2-memory"
        assert command[command.index("--repeat") + 1] == "1"

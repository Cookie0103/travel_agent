"""测试进程里拒绝真实调用：pytest下误触--live会产生费用，必须显式放行。"""

import os
import sys


def refuse_live_under_pytest(live: bool) -> None:
    if (
        live
        and "PYTEST_CURRENT_TEST" in os.environ
        and os.environ.get("TRAVEL_ALLOW_LIVE_IN_TESTS") != "1"
    ):
        print(
            "拒绝：pytest进程内不允许--live（如确需，设置TRAVEL_ALLOW_LIVE_IN_TESTS=1）",
            file=sys.stderr,
        )
        raise SystemExit(2)

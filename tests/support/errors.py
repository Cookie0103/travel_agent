"""测试共用的服务错误断言。"""

import pytest

from backend.services.common import ServiceError


def assert_error(
    failed: pytest.ExceptionInfo[ServiceError], status: int, code: str, reason: str = ""
) -> None:
    """服务错误的HTTP状态、错误类别与稳定reason标签都要断言，不只看抛了异常。"""
    error = failed.value
    assert (error.status, error.code, error.reason) == (status, code, reason)

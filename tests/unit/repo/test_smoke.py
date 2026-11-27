"""骨架冒烟检查：保证已声明的包边界能够在无凭据环境中导入。"""

import importlib


def test_project_packages_import_without_runtime_services() -> None:
    for name in ("backend.domain", "backend.api", "backend.providers", "mock_supplier", "eval"):
        assert importlib.import_module(name).__name__ == name

"""对临时包运行真实 import-linter：证明三条分层规则会拦截违规调用链。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def lint_temporary_project(
    tmp_path: Path, modules: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """复制配置而不复制实现，用小型导入图验证契约语义。"""
    config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(config, encoding="utf-8")
    for package in ("backend", "mock_supplier", "data", "eval"):
        for source in (ROOT / package).rglob("__init__.py"):
            target = tmp_path / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
    for module, content in modules.items():
        target = tmp_path.joinpath(*module.split(".")).with_suffix(".py")
        target.write_text(content, encoding="utf-8")
    env = os.environ.copy()
    env.update(PYTHONPATH=str(tmp_path), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from importlinter.cli import lint_imports_command; lint_imports_command()",
            "--no-cache",
            "--no-logo",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize(
    ("importer", "imported"),
    [
        ("backend.domain", "backend.api"),
        ("backend.domain", "mock_supplier"),
        ("backend.domain", "httpx"),
        ("backend.agent", "anthropic"),
        ("backend.tools", "claude_agent_sdk"),
        ("backend.services", "openai"),
        ("data", "mcp"),
        ("backend.api", "backend.persistence"),
        ("backend.api", "backend.domain"),
    ],
)
def test_forbidden_layer_import_is_rejected(tmp_path: Path, importer: str, imported: str) -> None:
    result = lint_temporary_project(tmp_path, {f"{importer}.example": f"import {imported}\n"})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "BROKEN" in result.stdout, result.stdout + result.stderr
    assert imported in result.stdout


def test_api_can_use_persistence_indirectly_through_service(tmp_path: Path) -> None:
    result = lint_temporary_project(
        tmp_path,
        {
            "backend.api.example": "import backend.services.example\n",
            "backend.services.example": "import backend.persistence\n",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("boundary", ["providers", "adapters", "mcp"])
def test_sdk_import_is_allowed_inside_designated_boundary(tmp_path: Path, boundary: str) -> None:
    result = lint_temporary_project(tmp_path, {f"backend.{boundary}.example": "import httpx\n"})
    assert result.returncode == 0, result.stdout + result.stderr

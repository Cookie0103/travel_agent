"""容器启动前迁移并导入版本化快照；复用现有入口，不初始化用户或下订单。"""

import asyncio

from alembic import command
from alembic.config import Config

from backend.persistence.database import ROOT
from data.import_catalog import main as import_snapshot


def main() -> None:
    command.upgrade(Config(str(ROOT / "backend/persistence/alembic.ini")), "head")
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(import_snapshot())


if __name__ == "__main__":
    main()

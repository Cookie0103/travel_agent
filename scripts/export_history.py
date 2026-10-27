"""只读导出用户旅行与最终对话记录；凭据只从环境/参数读取，不打印到日志。"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.persistence.database import Database, configuration, database_url
from backend.services.common import ServiceError
from backend.services.history import HistoryService


async def export(args: argparse.Namespace) -> None:
    config = configuration()
    if args.database_url:
        config["DATABASE_URL"] = args.database_url
    database = Database(database_url(config))
    try:
        result = await HistoryService(database).export(args.user, args.session)
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 输出本身包含用户私有对话；由操作者选择本地位置，不输出到 stdout。
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    finally:
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", help="默认读取 DATABASE_URL；地址不会打印")
    parser.add_argument("--user", type=UUID)
    parser.add_argument("--session", type=UUID)
    parser.add_argument("--out", required=True, help="新 JSON 文件路径，不覆盖已有文件")
    try:
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(export(parser.parse_args()))
    except (ValueError, OSError, ServiceError):
        print("导出失败：请核对连接、筛选条件及输出路径；已有文件未覆盖。", file=sys.stderr)
        return 1
    print("只读导出完成。输出包含私有对话，请保存在本地。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

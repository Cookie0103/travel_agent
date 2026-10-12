# 数据文件与导入程序

保存景点快照、攻略段落、测试样本和可重复执行的导入程序。
当前 `fixtures/kyoto.json` 含 20 景点和 12 段自编攻略供 M0 测试。
室内/类别标签是测试设置，营业时间未知；不是实时旅行资料。
`snapshots/`含146个OSM对象及中文Wikivoyage京都条目；来源/版本/哈希和数据许可随目录保存。
运行 `uv run python scripts/dev.py db-migrate` 后，`uv run python -m data.import_catalog` 导入166条记录；重复执行按来源ID更新，不新增重复项。
字段未知保留null，way/relation坐标是包围盒中心；原文含历史资料，不代表实时事实。
CLI的M0查询使用fixture；API旅行工具已查询数据库快照。
`supplements/kyoto-matcha-v1/`是带原来源/许可的独立抹茶开发数据，冲突营业时间保持未知。
显式补充导入：`uv run python -m data.import_catalog --snapshot-dir data/supplements/kyoto-matcha-v1`；upsert不删除原目录，不改变默认166条快照。
独立开发评测用`--database --catalog-dir data/supplements/kyoto-matcha-v1 --case-id kyoto-matcha`，实际manifest记录新数据hash，禁止当作原冻结集同版本结果。
fixtures/hotels.json含6家虚构酒店/12房型组合；金额为模拟数据，完整报价通过Evidence存入数据库。

数据库本身运行在 PostgreSQL 中；表映射、迁移和数据库读写代码放 backend/persistence。
旅行请求、行程等业务对象和规则放 backend/domain。

关键流程：获得有来源的数据 → 清洗/导入 → 交给业务查询使用。
不变量：保留数据来源与许可，不把内部参考仓库原文件复制进来。

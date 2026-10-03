# 数据文件与导入程序

保存景点快照、攻略段落、测试样本和可重复执行的导入程序。
当前 `fixtures/kyoto.json` 含 20 景点和 12 段自编攻略供 M0 测试。
室内/类别标签是测试设置，营业时间未知；不是实时旅行资料。
`snapshots/`含146个OSM对象及中文Wikivoyage京都条目；来源/版本/哈希和数据许可随目录保存。
运行 `uv run python scripts/dev.py db-migrate` 后，`uv run python -m data.import_catalog` 导入166条记录；重复执行按来源ID更新，不新增重复项。
字段未知保留null，way/relation坐标是包围盒中心；原文含历史资料，不代表实时事实。
CLI的M0查询仍默认使用fixture；M1.4旅行执行器再接入数据库查询。

数据库本身运行在 PostgreSQL 中；表映射、迁移和数据库读写代码放 backend/persistence。
旅行请求、行程等业务对象和规则放 backend/domain。

关键流程：获得有来源的数据 → 清洗/导入 → 交给业务查询使用。
不变量：保留数据来源与许可，不把内部参考仓库原文件复制进来。

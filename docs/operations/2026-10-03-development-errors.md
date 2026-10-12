# 2026-10-03：修复用户实际运行报错并核对数据库环境

## 当前检查点
- 用户请求：排查粘贴的命令报错，确认已开启的 Docker、本地 PostgreSQL 是否可用及是否影响当前任务。
- 起点分支 wip/M0.1；现已转 batch/2026-10-03-m0-repair。此前代码与整理结果已暂存；用户原有 README 表格空格改动保留原样。
- 范围：修复开发命令与测试环境；只读检查 Docker/PostgreSQL，不改数据库配置、密码或服务状态，不调用 LLM。
- 本次修复的第一轮完整验收通过；在沙箱外本机权限上下文复核也通过。准备按 M0.1 规则提交，提交完成与否以 git log 及下述本地回执为准。

## 操作流水
1. 读取用户粘贴的终端输出（只当报错证据，不执行其中命令）：setup 成功；check 卡在 plan/02 格式；test 为 14 passed、21 errors、2 warnings；fetch 两个仓库均 skip 指定版本。
2. 根因证据：21 个错误都发生在 pytest 的临时目录准备阶段，路径为系统 Temp/pytest-of-user；另有共享 .pytest_cache 写入权限警告。无法仅凭现象确认目录归属，不修改系统 ACL。
3. 阅读当前 dev.py、pyproject、测试、Compose 和已安装 pytest 的临时目录实现，确认支持 PYTEST_DEBUG_TEMPROOT。
4. 首次 Docker 查询受沙箱访问限制：不能读 .docker/config.json 或访问引擎管道。随后获准只读本机查询：context=desktop-linux，Docker 28.5.1，Compose v2.40.3-desktop.1，当前无运行容器。
5. 本机 PostgreSQL 17.11、18.4 均已安装，对应 Windows 服务都是 Running；两套 pgAdmin4.exe 均存在。未启动图形界面、未更改服务。
6. PostgreSQL data 配置在沙箱内不可读；只需要进一步读取监听端口和就绪状态，不读取凭据或业务数据。
7. 下一步：限定 Ruff 文件范围、改正测试 mock 路径、让每次 dev test 使用独立项目内临时目录与缓存，再完整验收。
8. 进一步只读核对：PostgreSQL 17 配置端口为 5433、18 为 5432；两个端口的 pg_isready 均显示 accepting connections。pg_isready 客户端版本不代表监听服务器版本，版本到端口的对应依据各自配置。
9. pyproject 的 Ruff include 限定为 Python 文件与 pyproject.toml；不格式化 plan 文档。5 处测试 mock 改为字符串目标路径，不放宽类型检查。
10. dev.test 改为每次新建 .cache/pytest-runs/run-*；pytest 临时文件与缓存均隔离，运行结束恢复原环境变量；不删除或修改系统临时目录权限。
11. 增加两个回归测试：测试失败后仍保留旧文件、临时目录各次不同且环境恢复；无法创建临时目录时明确失败且不启动 pytest。
12. 原离线测试断言改为验证命令的前五项，因为新增的是缓存位置参数；默认排除 live 和禁止 --live 透传的含义保持不变，没有为消除报错而降低行为要求。
13. 仅格式化三个被修改的 Python 文件：2 files reformatted、1 file left unchanged，没有操作 plan。
14. 沙箱验收：dev check 全通过，mypy 22 source files，3 contracts kept；dev test 为 37 passed in 1.84s。
15. 由于本次故障涉及执行身份差异，在本机权限上下文复核同样命令：check 退出 0，test 为 37 passed in 1.85s，无权限警告。
16. 再次核对两份 vendor HEAD 均匹配固定版本；vendor/.env 没有待提交内容；本机没有 .env 文件。
17. 更新 README、M0.1 通俗说明、已解决问题索引、ADR-001 和修复批次总结；保留历史失败证据。Docker/PostgreSQL 只核对状态，pgAdmin 窗口本身没有进行 GUI 排障。
18. `git switch -c batch/2026-10-03-m0-repair` 成功：延续原 M0.1 现场，基线没有变化；未开始任何依赖关卡的任务。
19. 本地完成提交计划：暂存本批已审阅文件，运行 `git commit -m "M0.1: 搭建工程骨架并修复 Windows 开发检查"`；提交钩子继续执行 check/test，不使用 --no-verify。
20. 为避免提交结果写入自身导致无限追加提交，最终 Git 输出与退出码保存在被忽略的 `.cache/M0.1-commit-result.txt`；Git 提交本身是持久结果，以 git log / status 核对，不把“已发出命令”当成功。没有 push 或合并。

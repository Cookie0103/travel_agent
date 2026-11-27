# 自动测试

入口：`uv run python scripts/dev.py test`（专项：`--path tests/unit/domain/test_repair.py`、`--keyword 名称`）。默认排除 live，不调用真实模型。分层、环境要求、CI 和已知的环境相关失败见[测试总览](../docs/handbook/testing/README.md)。

## 目录

```text
tests/
  unit/           离线单元测试，按被测代码所在的层分目录
    domain/         backend/domain：行程、酒店、条件、记忆的纯规则
    services/       backend/services、api、persistence：用例服务、限流、配置
    tools/          backend/tools、mcp：工具契约、围栏、MCP 桥接
    agent/          backend/agent：系统提示词、离线夹具运行时
    providers/      backend/providers、limits、profile：SDK 运行时、预算、模型 HTTP
    adapters/       backend/adapters：乐天、地图、天气、追踪
    eval/           eval/：题库加载、评分、评审、报告
    repo/           仓库级检查与开发脚本：分层契约、文档入口、dev.py、离线默认
  integration/    需要真实 PostgreSQL，按业务领域分目录
    api/ travel/ hotels/ plans/ memory/ sdk/ eval/ schema/
    conftest.py 与公用进程替身（api_process、sdk_helper、user_turn 等）留在本层
  live/           真实外部接口探针，需显式授权，默认不跑
  support/        公用替身与断言：fakes、runner、cli、errors、model_bodies
  fixtures/       接口结构样本（人工合成 JSON）与旧版模型定义
  conftest.py     把 pytest 临时目录放进 .cache
```

## 新测试放哪

- 测某个模块的纯逻辑：`tests/unit/<该模块所在的层>/test_<主题>.py`。
- 要连数据库或跨服务走完整链路：`tests/integration/<领域>/test_<主题>.py`，加 `@pytest.mark.integration`。
- 每个目录都有 `__init__.py`，跨文件引用写完整包路径，例如 `from tests.integration.travel.test_travel import travel_setup`。
- 在测试里取仓库根目录用 `Path(__file__).resolve().parents[N]`：`unit/<层>/` 和 `integration/<领域>/` 下 N=3。

## 不变量

- 默认不调用真实模型和真实供应商；事务与恢复测试用真实 PostgreSQL，不替换数据库实现。
- 流程：准备正常或错误场景 → 调用被测代码 → 检查结果是否符合规则。不为通过而改断言或跳过检查。

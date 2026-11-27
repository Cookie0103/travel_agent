# 2026-10-19 前端瘦身与文档对齐

承接 [会话记录](2026-10-19-session-log.md)。范围：`apps/web/**` 与文档；后端代码未动（仅 `pyproject.toml` 一处注释）。

## 前端

| 项 | 证据 | 动作 | 结果 |
| --- | --- | --- | --- |
| a. 422 `detail:[{loc}]` 分支 | `backend/api/app.py:94-109` 已把所有 `RequestValidationError` 转成 `{code,message}` | 删除 `apiError` 中的 422 分支与对应测试，保留通用文案“请求失败（status）”和 code 保留测试 | 完成 |
| b. `RunPage` 导出 | 仅 `api.ts` 内部使用，无外部导入 | 去掉 `export` | 完成 |
| c. Banner `info` | 全部调用点只用 `error`/`warning`；`.banner-info` 无引用 | 删除类型成员与 CSS 规则 | 完成 |
| d. 6 个别名 token | grep `var(--color-…)` 与 `bg-/text-/border-` 工具类、`text-3xl` 均无使用 | 从 `tokens.css` 删除 `--color-accent/success/warning/error/info`、`--text-3xl` | 完成 |
| e. 旧酒店链接回退 | `api-types` 中输出卡片的三个 url 字段为可选，持久化的旧卡片可缺这些键；回退链接“旧报价链接”是旧数据唯一可点入口 | 不动 | 跳过：删除会让旧已存会话的报价入口消失，属行为变更而非死代码；`hotel-links.test.ts` 同时覆盖不安全链接，保留 |

`history.ts:39` 按要求不动。验证：`uv run python scripts/dev.py web-check` 通过（typecheck、eslint、prettier、测试、build）。

## 文档

| 项 | 证据 | 动作 |
| --- | --- | --- |
| 分层债务 | `tools` 契约已无 ignore；`lint-imports` 11 kept / 0 broken；登记数 adapters 1、services→tools 2、services→providers 6、providers/agent→services 4 | 删除过期末行；契约第 5 条改“无登记”；`pyproject.toml` 去掉过期注释和空 `ignore_imports` |
| 模块地图 | 实际目录 `backend/` 含 server/cli/limits/profile/trace_log 与 `tools/skills` | 在 `layering-debt.md` 增“backend 模块地图（2026-10-19）”作为唯一说明；ARCHITECTURE、backend/README 补行并链接 |
| 当前批次指针 | `ARCHITECTURE.md`、`AGENTS.md`、`docs/README.md` 指向旧批次 | 改为 `2026-10-19-session-log.md`，分支 `batch/2026-10-19-architecture-hardening`；文件数改“370 多个” |
| README.md | `plan/` 目录不存在；迁移已到 0023；CI 已在 PR #9 绿 | 改 docs/plans；删“建好了目录不代表…”；迁移指向 `versions/`；CI 句改为已运行通过 |
| docs/tasks/M0.md | “三条分层规则”过时 | 改为 11 条契约；`protocol-deepseek.md` 历史文本不动 |

跳过：`ARCHITECTURE.md` 保持 34 行（上限 100）。

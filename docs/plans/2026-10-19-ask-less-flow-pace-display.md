# ask-less 第二轮补充：节奏默认假设的可见展示

## 问题

第二轮让未指定节奏时默认按“标准”规划，但默认值只写在助手文字里，“旅行条件”面板看不到，用户无从知道系统做了假设。

## 做法（纯前端派生）

- `apps/web/src/lib/pace.ts` 新增 `paceLabel(pace)`：已指定显示“节奏：X”；未指定（`currentPace` 返回空）显示“节奏：标准（默认假设，未指定）”。
- `trip-panel.tsx` 条件视图单独一行展示，未指定时用 `muted` 样式。
- 不写入存储的 request，不改 `explicit_fields`、来源/溯源；默认值仍不算用户显式。
- 测试：`apps/web/tests/pace.test.ts` 的 `paceLabel` 用例。
- 面板在“还没有设定条件”空状态下不显示该行（避免空面板里出现假设）。

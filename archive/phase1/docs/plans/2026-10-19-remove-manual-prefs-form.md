# 移除偏好面板的手动编辑表单（方案 A）

## 背景与用户决定

偏好现在由对话抽取、用合并确认卡（memory-choices.tsx）确认，偏好面板里手填的表单与此重复。用户最终决定（方案 A）：删除整块手动编辑区，只保留已确认偏好列表及其逐条“删除”。

## 删除了什么

`apps/web/src/components/preferences.tsx`：
- 控件：“兴趣（每行一项）”文本框、“其他偏好（每行一项）”文本框、“偏好交通”下拉，以及按钮“保存偏好”“清除偏好”（含 Popover 二次确认）“读取最新偏好”“更新我的画像”，整个 `<form>`。
- 函数/状态：`change()`（PATCH/DELETE `/preferences`）、`updateProfile()`（POST `/profile-summary`）、`display()`、`interests/constraints/transport/confirmClear` 状态、`dirty`/`dirtyRef` 与“未保存编辑不被后台刷新覆盖”的逻辑、`load(force)` 的 force 参数。
- 引入的 `Popover*`（`ui/popover.tsx` 本身仍被 `hover-popover.tsx` 使用，保留）。

`apps/web/src/lib/preference-form.ts`：删除 `preferenceLines`、`isDirty`、`PreferenceForm` 类型（仅表单使用）；文件保留，因 `factGroups`、`factStatus` 仍被面板使用。

`apps/web/src/app/globals.css`：删除“Preferences form”整段样式（`.preference-panel form/label/select/textarea`）。

测试 `apps/web/tests/preference-form.test.ts`：删除用例“lines trims and drops blanks; dirty compares against saved values”（被测函数已删）；保留 factGroups/factStatus 用例。

## 保留了什么

- 已确认/待确认偏好列表、状态显示、每条的“删除”按钮（`forget`，DELETE `/memory/{id}`）、“其他旅行的临时偏好”折叠、历史版本折叠。
- Run 结束时按 `refreshKey` 刷新、折叠时不请求（`active`）。
- 版本号标签、`onChanged` 回调（删除后刷新工作区）。
- 只读的画像文字展示（读 GET `/profile-summary`）；因“更新我的画像”按钮已删，画像不会再被前端重新生成，可能变旧，是否一并移除待负责人决定。
- `use-long-term-pace.ts`、`memory-choices.tsx` 未改动。
- 说明文案改为“在对话中逐条确认的偏好会保存，可随时删除”。

## 后端哪些接口因此无人调用（未改后端）

- `PATCH /preferences`（手动保存）
- `DELETE /preferences`（清除全部）
- `POST /profile-summary`（生成画像）

仍在用：`GET /preferences`、`GET /memory`、`DELETE /memory/{id}`、`GET /profile-summary`。前端没有单独的 API 封装函数，调用都在组件内联，故 `api.ts` 无需改；`api-types.ts` 由后端 schema 生成，未动。

另：`docs/adr/025-derived-user-profile.md`、`docs/design/03-data-tools.md` 仍写着“点击更新我的画像”，不在本次所有范围内，未改，需要后续同步。

## 测试

`uv run python scripts/dev.py web-check`（类型、eslint、prettier、测试、构建）全部通过。

## 没在真浏览器验证

只做了静态检查、单元测试和构建，没有在真浏览器里打开偏好面板确认布局（去掉 form 后列表、画像文字、状态提示的间距）与删除交互。

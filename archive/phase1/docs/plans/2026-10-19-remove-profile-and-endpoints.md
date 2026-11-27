# 2026-10-19 移除画像文字块与未使用的后端端点

## 背景与用户决定

手动偏好编辑区已从网页偏好面板移除（见[remove-manual-prefs-form](2026-10-19-remove-manual-prefs-form.md)）。此后网页不再调用 `PATCH /preferences`、`DELETE /preferences`、`POST /profile-summary`，只读“画像”文字也无法再生成。用户最终决定：(1) 删除网页里的只读画像文字块；(2) 删除不再使用的后端端点及相关死代码；更新 ADR-025（加日期注记，不改写历史）与 `docs/design/03-data-tools.md` 中“点击更新我的画像”的措辞；不删 DB 列/表。

## 用法追踪（有证据）

- 画像注入模型上下文：`backend/services/travel.py:277` 的 `business_context` 把 `UserProfileService.snapshot(...).text` 放进 `profile_summary`；`backend/providers/claude_agent/database_tools.py:139` 在偏好消融时移除它。`tests/integration/test_user_profile.py` 断言了注入值。所以画像**仍被模型上下文使用**，存储与快照读取必须保留。
- 画像生成的唯一调用方是 `POST /profile-summary`（`UserProfileService.generate`）；eval/scripts 没有任何调用。删除端点后生产路径无法生成新画像。
- 作废：`invalidate_profile` 被 `services/memory.py:499,533` 和 `services/preferences.py:54,75` 使用，保留。
- `GET /profile-summary`：网页是唯一调用方（`preferences.tsx` 两处）；tests 之外无其它调用，块删除后无人调用，删除。
- `PreferenceService.change` / `PreferencePatch` / `PreferenceVersion`：被 `eval/state.py`、`eval/memory_metrics.py` 及 10 余个集成测试直接使用（种子偏好、全部遗忘、墓碑与召回边界），保留。HTTP 之外 `PATCH/DELETE /preferences` 只有 `app.py` 两个路由包装。
- `GET /preferences`：网页仍用，保留。`DELETE /memory/{id}`、`GET /memory*` 保留。

## 删除了什么

- `apps/web/src/components/preferences.tsx`：`UserProfile` 类型、`profile` 状态、两处 `/profile-summary` 请求与画像文字块。
- `backend/api/app.py`：`PATCH /preferences`、`DELETE /preferences`、`GET /profile-summary`、`POST /profile-summary` 四个路由，及不再使用的 `PreferencePatch`、`UserProfileService/UserProfileView` 导入与 `profile` 实例。
- 重新生成 `data/contracts/web-openapi.json`、`apps/web/src/lib/api-types.ts`（四个操作与 `PreferencePatch`、`UserProfileView` 模式随之消失）。
- 文档：ADR-025 加 2026-10-19 注记；`03-data-tools.md` 画像句改为“入口已移除”；`02-architecture.md` 路由表改为只列 `GET /preferences`。

## 保留了什么及原因

- `UserProfileService`（含 `get/generate`）、`domain/user_profile.py`、`persistence/user_profile.py`、`PROFILE_RUBRIC`/`profile` 评审角色、`user_profile_summaries` 表：画像仍注入模型上下文，且 ADR-011 的角色闭集与“不删列/表”决定牵涉其中。`generate` 现在在生产路径上不可达（休眠代码，仍有服务层测试覆盖）。是否彻底删除生成代码并同时去掉注入，是产品决定，留待用户另行确认；ADR-025 注记已写明。
- `PreferenceService.change` 与全部相关模型：见上，eval 与测试依赖。
- 不变量：记忆确认规则、围栏、召回边界、事实变更同事务作废画像均未改动。

## 测试

- `test_user_profile.py`：删除 `test_profile_api_is_owner_scoped_and_disabled_generation_does_not_charge`（只测被删的 GET/POST 端点）；其余服务层测试保留。
- `test_preferences.py`：HTTP 版 `first_empty_delete...` 改为服务层同语义；`test_api_preferences_are_owned_partial_versioned...` 拆成 `test_api_get_preferences_is_owned_and_removed_write_routes_are_gone`（GET 归属 + 已删路由返回 405/404）与 `test_service_partial_versioned_change_and_delete_keeps_tombstone`（服务层的部分更新/版本/墓碑）；`test_invalid_preference_input...` 改为直接校验 `PreferencePatch` 模型拒绝非法输入（原 422 来自同一模型）。
- `test_input_limits.py::test_nul_in_preferences_and_request_is_422`：偏好部分改为模型拒绝 NUL，并断言 `PATCH /preferences` 为 405；会话 request 的 422 断言不变；删去末尾依赖 PATCH 成功的断言。
- `test_memory.py::test_memory_api_owner_history_and_delete`：原用 `PATCH /preferences` 造种子，改为服务层 `PreferenceService.change` 种子，其余断言不变。
- 验证：`dev.py check`、`dev.py web-check` 通过；相关 pytest（preferences/user_profile/input_limits/memory）46 通过。完整 `dev.py test` 结果见交付报告。

## 没在真浏览器验证

未启动浏览器检查偏好面板。仅有类型检查、lint、prettier 与既有组件级测试；画像块移除后的页面外观与删除单条偏好后的刷新流程未目视确认。

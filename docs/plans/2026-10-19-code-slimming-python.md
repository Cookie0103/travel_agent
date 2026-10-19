# 2026-10-19 Python 侧瘦身记录（backend / eval / scripts / tests）

范围：只动 backend/**、eval/**、scripts/**、tests/**、mock_supplier/**。验证：`scripts/dev.py check` 全绿（11 条契约 0 broken），完整 `scripts/dev.py test`：2283 passed, 1 skipped, 0 failed。

净行数（`git diff --shortstat -- backend eval scripts tests mock_supplier`，含新增的 3 个测试辅助文件）：104 files，+396 / -459，净减 63 行。

## 1. eval 与 dev 的过期里程碑措辞
- 证据：`eval/run.py` 早已存在；`eval/__init__.py` 却写“当前没有 eval.run”；`scripts/dev.py` 守卫文案写“等待 M0.6”。tests/test_dev.py 的 `test_unimplemented_evaluation_*` 只断言返回 1 且不启动进程，不依赖文案。
- 动作：改写 `eval/__init__.py` 文档；守卫保留，docstring 与提示改为“缺少 eval/run.py，无法运行评测”。
- 结果：文案准确，测试通过。

## 2. fetch_upstream 警告
- 证据：warning 含 “M0.1 继续；M0.6 前再处理”。
- 动作：改为“非必需上游，已跳过。”，模块 docstring 去掉 M0.1。

## 3. Price.attempt_charge
- 证据：全仓（backend/eval/scripts/tests）仅定义处出现，无读取。
- 动作：删字段与 4 处第三个位置参数；复核 USD 两项剩余位置参数为 (input, output, input_limit, cache_write_multiplier, currency)，与字段顺序一致；ruff format。
- 结果：test_protocol_probe / test_sdk_providers 通过。

## 4. missing_room_choices
- 证据：生产代码无调用，仅 tests/test_room_preferences.py 一处导入。
- 动作：删函数。该测试原断言 `"bed" not in missing_room_choices(...)`，改为 `len(ROOM_CHOICES["bed"] & recognized_room_choices(...)) == 1`（语义等价：床型组恰有一个已识别值），未放宽。

## 5. mcp/server 重复 loop_factory
- 证据：与 backend/server.py 的实现完全相同，无其他引用。
- 动作：uvicorn 的 loop 改为 `backend.server:loop_factory`，删副本及不再使用的 `import asyncio`。

## 6. KYOTO -> TOKYO 与内联 ZoneInfo
- 证据：`KYOTO = timezone(+9, "Asia/Tokyo")`；24 处使用（domain/repair、validator、opening_hours、tools/travel）。scripts/probe_hotel_sort.py 的 `KYOTO` 是另一个 GeoPoint（京都），不是同一常量，未改。
- 动作：改名 TOKYO；`domain/travel_request.tokyo_today()` 用 TOKYO（domain 内部 import opening_hours，无新增外向依赖）；adapters/open_meteo、agent/fixture_runtime 改用 `tokyo_today()`；agent/demo、eval/simulator_metrics、eval/state 改用 TOKYO。日本无夏令时，固定偏移与 ZoneInfo 取值相同。
- 保留：`timezone: Literal["Asia/Tokyo"]` 字段值与 open_meteo 请求参数里的字符串（是协议值，不是时区构造）；tests 内 ZoneInfo 未动。

## 7. 未用参数
- `persistence.travel.recent_evidence(..., revision)`：函数体不使用，删参数与唯一调用方。
- `Budget.daily_limit(self, now)`：`now` 未使用，改为无参；`Budget.reserve` 内调用与 tests/test_human_no_daily_cap.py 两处调用同步修改。
- 注意：`Settings.daily_limit` 是另一个 property，未动。

## 8. TravelService.get_request -> read_request
- 证据：backend 内无调用；测试 129 次 + eval 6 次（`.get_request(` 精确匹配，`get_request_view` 不受影响）。
- 检查：test_booking_concurrency 的调用仅是读取 revision 后搜索酒店，不是锁屏障；test_lock_free_read_callers 本来就用 read_request。没有测试依赖“调用后 travel_requests 空行已被创建”（完整集成测试通过为证）。
- 动作：全部机械改名，删除 `TravelService.get_request`。无需保留带锁调用。

## 9. 兼容代码
- 已删：`services/travel.py` 中 `field_sources` 缺失时重放旧幂等回执的分支（约 20 行）。同时删除其专属测试：
  - tests/integration/test_condition_sources.py::test_legacy_tool_patch_replay_uses_actual_old_key_without_inventing_source（直接测被删分支）；
  - tests/integration/test_conversation_state.py::test_nonempty_constraint_removal_cannot_replay_legacy_no_removal_receipt（前置条件是构造旧回执，分支删除后该防护已无对象；移除约束的正常路径由其他测试覆盖）。
- 未动（报告）：`persistence/travel.py::LEGACY_DETAIL_FIELDS`（hotel_info_url / plan_list_url / reservation_url）并非读取回退，而是“这三个键即使为 None 也写入侧列”，保持旧读写者看到的 payload 形状。后端删除它会改变存量/新写入 payload 形状，且 apps/web/src/lib/hotel-links.ts 仍对这三个字段缺失做兜底；两侧应一起决定，本轮 backend 不单独删。后端没有别的酒店 URL 回退代码。
- 保留：legacy_request/LegacyRequestSnapshot（ADR-015 双写）、Budget.legacy 账本。

## 10. 测试整理
- `tests/cli.py::requires_claude_cli`：基于 `find_cli(os.environ)`（尊重 TRAVEL_CLAUDE_CLI，Windows 要求 .exe），替换 16 个文件共 22 处 `skipif(not shutil.which("claude"))`；原各不相同的 reason 统一为一句。语义变化：配置了 TRAVEL_CLAUDE_CLI 但 PATH 无 claude 时也会运行。
- `tests/runner.py`：`selector_runner()` 与 `SELECTOR_OPTIONS`。替换 tests 下 26 处 `asyncio.Runner(loop_factory=asyncio.SelectorEventLoop)`、`backend_options` 的重复字面量与 5 处局部 `options` 变量；共 28 个文件。tests/test_event_loop_entrypoints.py 通过（AST 检查不再看到裸 Runner）。未改 eval/database.py 与 scripts/ 内已有的 Selector Runner（生产代码不应依赖 tests 包）。
- `tests/model_bodies.py`：`request_body` 与 `response_body` 从 tests/test_sdk_guard.py 移出（10 个测试文件跨文件导入，同样一并改为从此处导入）。
- tests/test_architecture.py 文档“三条”改为 11 条契约说明；未做逐契约参数化（现有参数化为抽样，逐契约需为每条构造违规样例，不算 trivial）。

## 未做（按指示）
ProbeError 改名、TOOL_NAME 改名、cost 键统一、users.preferences/source_turn_id/ExternalApiUsageRow/GoogleCoordinateRow、裸 pytest.raises 转换。

## 测试改动汇总
- 删除 2 个测试（见 9，原因：被测兼容分支已删除）。
- 改写 1 个断言（见 4，语义等价）。
- 其余均为机械改名/导入替换，无断言被放宽。

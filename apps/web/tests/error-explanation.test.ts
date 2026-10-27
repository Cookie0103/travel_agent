/** Errors are explained without leaking arbitrary error text or misdiagnosing credentials. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { errorExplanation } from "../src/lib/error-explanation.ts";
const cases = [
  ["validation", "校验未通过：条件或修改不符合要求，请核对相关信息。"],
  ["blocked", "操作受限：请检查操作前提或调用限制。"],
  ["unavailable", "服务不可用：请稍后重试读取；此次失败不等于已保存数据丢失。"],
  ["timeout", "响应超时：已完成的步骤仍保留；超时不代表密钥或额度有误。"],
  ["rate_limited", "调用受限：请求过于频繁或达到限额，请稍后重试。"],
  ["provider_error", "外部服务异常：本次未取得可用结果，请稍后重试。"],
  [
    "conflict",
    "状态冲突：条件存在冲突或行程版本已变化，请核对条件并读取最新状态。",
  ],
  ["cancelled", "已取消：已完成的步骤仍保留。"],
] as const;
for (const [code, wanted] of cases) {
  test(`${code} explains its cause and next step in Chinese`, () => {
    assert.equal(errorExplanation(code), wanted);
  });
}
test("unknown codes and inherited property names never echo internal parameters", () => {
  for (const code of [
    "request_id=private;token=not-a-real-secret",
    "constructor",
    "toString",
    "",
    null,
    undefined,
  ]) {
    assert.equal(
      errorExplanation(code),
      "原因暂不明确：请读取最新状态或稍后重试。",
    );
  }
});
test("closed tool reasons explain the cause in Chinese and take precedence over the code text", () => {
  assert.equal(
    errorExplanation("blocked", "tool_call_cap"),
    "本轮工具调用次数已用完，请把剩余需求拆成下一条消息继续",
  );
  assert.equal(
    errorExplanation("blocked", "repair_limit"),
    "行程校验的修复次数已用完",
  );
  assert.equal(
    errorExplanation("blocked", "repeat_blocked"),
    "相同请求已被拒绝，未重复执行",
  );
});
test("legacy events without reason, other and arbitrary reasons keep the generic code text", () => {
  const generic = "操作受限：请检查操作前提或调用限制。";
  for (const reason of [
    undefined,
    null,
    "other",
    "constructor",
    "token=not-a-real-secret",
  ])
    assert.equal(errorExplanation("blocked", reason), generic);
});
test("tool reasons never explain run-level codes such as timeout", () => {
  assert.equal(
    errorExplanation("timeout", "repeat_blocked"),
    "响应超时：已完成的步骤仍保留；超时不代表密钥或额度有误。",
  );
  assert.equal(
    errorExplanation("blocked", "tool_call_cap"),
    "本轮工具调用次数已用完，请把剩余需求拆成下一条消息继续",
  );
});
test("object prototype keys as reason fall back to the code text", () => {
  for (const reason of ["__proto__", "constructor", "toString"])
    assert.equal(
      errorExplanation("blocked", reason),
      "操作受限：请检查操作前提或调用限制。",
    );
});
test("hotel validation reasons name the cause; unavailable uses them too", () => {
  assert.equal(
    errorExplanation("validation", "hotel_missing_fields"),
    "酒店查询缺少必要条件，请在对话中补充",
  );
  assert.equal(
    errorExplanation("unavailable", "hotel_external_unavailable"),
    "酒店数据源暂不可用，请稍后重试",
  );
  assert.equal(
    errorExplanation("unavailable", "constructor"),
    "服务不可用：请稍后重试读取；此次失败不等于已保存数据丢失。",
  );
});

test("local stops explain the actual cause and keep provider, timeout and cancel errors distinct", () => {
  const wanted = {
    request_limit:
      "本轮模型请求次数已用完，已完成的结果已保留；请再发一条消息继续",
    request_too_large:
      "本轮上下文超过请求大小上限，已完成的结果已保留；请缩小本次需求后继续",
    budget_limit: "本地费用预算或授权检查未通过，执行已停止；请核对可用预算",
    local_guard:
      "本地执行保护已停止本轮，已完成的结果已保留；请读取最新状态后继续",
  };
  for (const [reason, text] of Object.entries(wanted)) {
    assert.equal(errorExplanation("blocked", reason), text);
    for (const code of ["timeout", "cancelled", "provider_error"])
      assert.equal(errorExplanation(code, reason), errorExplanation(code));
  }
});

test("validation failures put a short Chinese server reason into the main message", () => {
  assert.equal(
    errorExplanation(
      "validation",
      "demo_failed",
      undefined,
      "固定演示仅覆盖京都二至三日游",
    ),
    "校验未通过：固定演示仅覆盖京都二至三日游。",
  );
});
test("detail text is ignored for other codes and when it could leak internals", () => {
  const generic = "校验未通过：条件或修改不符合要求，请核对相关信息。";
  assert.equal(
    errorExplanation("blocked", null, undefined, "固定演示仅覆盖京都"),
    "操作受限：请检查操作前提或调用限制。",
  );
  for (const detail of [
    "",
    null,
    undefined,
    "request_id=private;token=abc",
    "English only message",
    "详见 https://internal.example/x",
    "第一行\n第二行",
    "长".repeat(200),
  ])
    assert.equal(
      errorExplanation("validation", null, undefined, detail),
      generic,
    );
});

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

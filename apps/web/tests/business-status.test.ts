/** UI status is based on committed server tool facts, never on optimistic answer text. */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  runLabel,
  runStatus,
  runFailureMessage,
  runErrorMessage,
} from "../src/lib/business-status.ts";
import type { Run } from "../src/lib/api.ts";
const run: Run = {
  run_id: "run",
  session_id: "trip",
  status: "completed",
  mode: "offline",
  answer: "已通过，已保存",
  error_code: null,
  last_sequence: 3,
  created_at: "2026-10-08T00:00:00Z",
  presentations: [],
};
test("runtime completion cannot override stage failure or hard conflict", () => {
  assert.equal(
    runLabel({
      ...run,
      business_result: {
        kind: "stage_failed",
        code: "conflict",
        reason: "plan_exists",
      },
    }),
    "草稿未生成",
  );
  assert.equal(
    runLabel({
      ...run,
      business_result: {
        kind: "draft_staged",
        draft_id: "draft",
        plan_id: "plan",
        validation_status: "conflict",
      },
    }),
    "草稿有校验冲突，不能确认",
  );
});
test("staged is not saved; only server confirmation reports a formal version", () => {
  for (const status of ["complete", "partial"] as const) {
    assert.equal(
      runLabel({
        ...run,
        business_result: {
          kind: "draft_staged",
          draft_id: "draft",
          plan_id: "plan",
          validation_status: status,
        },
      }),
      status === "complete"
        ? "草稿已校验，尚未保存"
        : "草稿已暂存，部分可校验，尚未保存",
    );
  }
  assert.equal(
    runLabel({
      ...run,
      business_result: { kind: "confirmed", plan_id: "plan", version: 1 },
    }),
    "已确认行程 · V1",
  );
  assert.equal(
    runLabel({ ...run, business_result: { kind: "answer_only" } }),
    "回复完成",
  );
  assert.equal(runLabel(run), "回复结束，业务状态未提供");
  assert.equal(
    runLabel({
      ...run,
      status: "cancelled",
      business_result: {
        kind: "draft_staged",
        draft_id: "draft",
        plan_id: "plan",
        validation_status: "partial",
      },
    }),
    "已取消 · 草稿已暂存，部分可校验，尚未保存",
  );
});

test("unknown and prototype statuses have a Chinese fallback", () => {
  for (const status of ["new_status", "constructor", "toString", "__proto__"])
    assert.equal(runStatus(status), "状态暂不明确");
  assert.equal(runStatus("awaiting_user"), "等你操作");
});
test("run failures explain the real category without leaking codes or blaming credentials", () => {
  assert.equal(
    runFailureMessage("validation"),
    "执行未完成：校验未通过：条件或修改不符合要求，请核对相关信息。",
  );
  assert.equal(
    runFailureMessage("timeout"),
    "执行未完成：响应超时：已完成的步骤仍保留；超时不代表密钥或额度有误。",
  );
  assert.equal(
    runFailureMessage("constructor"),
    "执行未完成：原因暂不明确：请读取最新状态或稍后重试。",
  );
});

test("partial answers keep timeout and provider failure explanations, including history", () => {
  for (const error_code of ["timeout", "provider_error"] as const) {
    const failed = {
      ...run,
      status: "failed" as const,
      answer: "京都東急ホテル已有信息",
      error_code,
    };
    assert.equal(runErrorMessage(failed), runFailureMessage(error_code));
    assert.equal(failed.answer, "京都東急ホテル已有信息");
  }
  assert.equal(runErrorMessage(run), undefined);
  assert.equal(
    runErrorMessage({
      ...run,
      error_code: "conflict",
      business_result: {
        kind: "stage_failed",
        code: "conflict",
        reason: "plan_exists",
      },
    }),
    undefined,
  );
});
test("run failure shows the last failed tool reason, and legacy runs keep the generic text", () => {
  assert.equal(
    runFailureMessage("blocked", "repair_limit"),
    "执行未完成：行程校验的修复次数已用完",
  );
  assert.equal(
    runFailureMessage("blocked"),
    "执行未完成：操作受限：请检查操作前提或调用限制。",
  );
});
test("run failure with a timeout code ignores an earlier tool reason", () => {
  assert.equal(
    runFailureMessage("timeout", "repeat_blocked"),
    runFailureMessage("timeout"),
  );
});
test("run-level failure reasons are shown in Chinese and take precedence only for blocked/unavailable", () => {
  assert.match(
    runFailureMessage("blocked", "conversation_incomplete"),
    /^执行未完成：本轮在行程草稿完成前停止了.*继续排行程/,
  );
  assert.equal(
    runFailureMessage("unavailable", "conversation_state_unavailable"),
    "执行未完成：对话状态暂时读取失败，请稍后重试",
  );
  assert.match(runFailureMessage("blocked", "max_turns"), /轮数已用完/);
  // 运行级原因不能借给 timeout 等其他运行级错误码，未知原因仍用通用文本。
  assert.equal(
    runFailureMessage("timeout", "conversation_incomplete"),
    runFailureMessage("timeout"),
  );
  assert.equal(
    runFailureMessage("blocked", "made_up_reason"),
    runFailureMessage("blocked"),
  );
});

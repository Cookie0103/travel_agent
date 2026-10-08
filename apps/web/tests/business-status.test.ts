/** UI status is based on committed server tool facts, never on optimistic answer text. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { runLabel } from "../src/lib/business-status.ts";
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

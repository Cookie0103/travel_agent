/** Trusted failure reasons produce actionable guidance without model text or automatic writes. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { stageGuidance } from "../src/lib/business-status.ts";
import type { Run } from "../src/lib/api.ts";
const run: Run = {
  run_id: "run",
  session_id: "trip",
  status: "completed",
  mode: "offline",
  answer: "已保存。plan_id=private/internal",
  error_code: null,
  last_sequence: 3,
  created_at: "2026-10-08T00:00:00Z",
  presentations: [],
};
test("existing plan failure guides an edit or a new trip, never replacement or a claimed save", () => {
  assert.deepEqual(
    stageGuidance({
      ...run,
      business_result: {
        kind: "stage_failed",
        code: "conflict",
        reason: "plan_exists",
      },
    }),
    {
      message:
        "这个旅行已有正式行程。可以说明要改的部分，在原行程上生成修改草稿；如果是另一趟旅行，请新建旅行。",
      existingPlan: true,
    },
  );
});
test("invalid change and exhausted repairs provide different safe next steps", () => {
  assert.deepEqual(
    stageGuidance({
      ...run,
      business_result: {
        kind: "stage_failed",
        code: "validation",
        reason: "patch_invalid",
      },
    }),
    {
      message:
        "本次修改无法应用到现有行程，可能涉及已变化或锁定的项目。请先读取最新行程，再说明需要调整的部分。",
      existingPlan: false,
    },
  );
  assert.deepEqual(
    stageGuidance({
      ...run,
      business_result: {
        kind: "stage_failed",
        code: "blocked",
        reason: "repair_limit",
      },
    }),
    {
      message:
        "本轮校验与修复次数已用完，草稿未生成。请缩小要改的范围，确认条件后再发起一轮规划。",
      existingPlan: false,
    },
  );
});
test("unspecified failure uses a safe fallback; nonfailure and legacy replies get no guessed reason", () => {
  assert.deepEqual(
    stageGuidance({
      ...run,
      business_result: {
        kind: "stage_failed",
        code: "unavailable",
        reason: "other",
      },
    }),
    {
      message:
        "本次未能生成草稿。请读取最新状态，查看执行步骤中的失败类别后再试。",
      existingPlan: false,
    },
  );
  assert.equal(
    stageGuidance({ ...run, business_result: { kind: "answer_only" } }),
    undefined,
  );
  assert.equal(stageGuidance(run), undefined);
});

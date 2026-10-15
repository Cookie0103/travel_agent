import assert from "node:assert/strict";
import { test } from "node:test";
import { errorExplanation } from "../src/lib/error-explanation.ts";
import { toolCompletionState } from "../src/lib/external-status.ts";

const retry = {
  attempts: 2,
  waited_seconds: 1,
  provisional: false,
  kind: null,
  status: null,
  recovered_from: null,
  first_failure: null,
  retry_skipped: null,
  cap_scope: null,
  used: null,
  limit: null,
};
test("final error explains actual retry count", () => {
  assert.match(
    errorExplanation("rate_limited", null, { ...retry, kind: "rate_limited" }),
    /已重试1次/,
  );
});
test("provisional parameter error remains correcting instead of failed", () => {
  assert.equal(
    toolCompletionState("validation", {
      ...retry,
      attempts: 1,
      provisional: true,
    }),
    "correcting",
  );
  assert.equal(
    errorExplanation("validation", null, {
      ...retry,
      attempts: 1,
      provisional: true,
    }),
    "正在修正查询参数",
  );
});
test("quota skip explains no retry was sent", () => {
  const explanation = errorExplanation("blocked", null, {
    ...retry,
    attempts: 1,
    kind: "quota_exhausted",
    retry_skipped: "quota",
  });
  assert.match(explanation, /配额/);
  assert.match(explanation, /未执行重试/);
  assert.doesNotMatch(explanation, /已重试1次/);
});

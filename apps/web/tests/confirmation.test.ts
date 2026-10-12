/** Confirmation is a committed fact before its subsequent canonical read can fail. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, confirmPlan } from "../src/lib/api.ts";

test("a failed canonical read retains the confirmation receipt and never repeats the POST", async () => {
  const original = globalThis.fetch;
  const calls: string[] = [];
  let receipt: { plan_id: string; version: number } | undefined;
  globalThis.fetch = async (input, init) => {
    calls.push(`${init?.method} ${input}`);
    if (init?.method === "POST")
      return Response.json({ plan_id: "plan", version: 1 });
    assert.deepEqual(receipt, { plan_id: "plan", version: 1 });
    return Response.json({ message: "synthetic unavailable" }, { status: 503 });
  };
  try {
    await assert.rejects(
      confirmPlan("draft", "synthetic-token", (saved) => {
        receipt = { plan_id: saved.plan_id, version: saved.version };
      }),
      (error: unknown) =>
        error instanceof ApiError &&
        error.status === 503 &&
        error.message ===
          "确认已成功，正式行程读取失败。请重新读取，无需再次保存。",
    );
    assert.deepEqual(receipt, { plan_id: "plan", version: 1 });
    assert.deepEqual(calls, [
      "POST /api/plan-drafts/draft/confirm",
      "GET /api/plans/plan",
    ]);
  } finally {
    globalThis.fetch = original;
  }
});

test("a rejected confirmation never reports success or attempts a formal read", async () => {
  const original = globalThis.fetch;
  const calls: string[] = [];
  let acknowledged = false;
  globalThis.fetch = async (input, init) => {
    calls.push(`${init?.method} ${input}`);
    return Response.json({ message: "草稿已过期" }, { status: 409 });
  };
  try {
    await assert.rejects(
      confirmPlan("draft", "synthetic-token", () => {
        acknowledged = true;
      }),
      (error: unknown) => error instanceof ApiError && error.status === 409,
    );
    assert.equal(acknowledged, false);
    assert.deepEqual(calls, ["POST /api/plan-drafts/draft/confirm"]);
  } finally {
    globalThis.fetch = original;
  }
});

test("a post-confirmation authentication failure preserves 401 handling", async () => {
  const original = globalThis.fetch;
  let acknowledged = false;
  globalThis.fetch = async (_input, init) =>
    init?.method === "POST"
      ? Response.json({ plan_id: "plan", version: 1 })
      : Response.json({ message: "expired identity" }, { status: 401 });
  try {
    await assert.rejects(
      confirmPlan("draft", "synthetic-token", () => {
        acknowledged = true;
      }),
      (error: unknown) => error instanceof ApiError && error.status === 401,
    );
    assert.equal(acknowledged, true);
  } finally {
    globalThis.fetch = original;
  }
});

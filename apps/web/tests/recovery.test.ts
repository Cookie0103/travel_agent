/** Lost responses retain the business idempotency key and reload canonical confirmed plans. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { messageInput, readDraft } from "../src/lib/api.ts";

test("pending message survives serialization and explicit retry keeps its ID and mode", () => {
  const first = messageInput(undefined, "京都旅行", "live");
  const restored = JSON.parse(JSON.stringify({ pending_message: first }));
  assert.deepEqual(
    messageInput(restored.pending_message, "京都旅行", "live"),
    first,
  );
  assert.throws(() =>
    messageInput(restored.pending_message, "不同消息", "live"),
  );
  assert.throws(() =>
    messageInput(restored.pending_message, "京都旅行", "offline"),
  );
  assert.notEqual(
    messageInput(undefined, "京都旅行", "live").client_message_id,
    first.client_message_id,
  );
});
test("confirmed draft loads the canonical current plan without repeating confirmation", async () => {
  const original = globalThis.fetch;
  const paths: string[] = [];
  globalThis.fetch = async (path, options) => {
    paths.push(String(path));
    assert.equal(options?.method, "GET");
    return Response.json(
      String(path).includes("plan-drafts")
        ? { status: "confirmed", plan_id: "plan" }
        : { plan_id: "plan", version: 2 },
    );
  };
  try {
    const plan = await readDraft("draft", "local-test");
    assert.equal(plan.version, 2);
    assert.deepEqual(paths, ["/api/plan-drafts/draft", "/api/plans/plan"]);
  } finally {
    globalThis.fetch = original;
  }
});

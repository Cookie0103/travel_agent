/** Lost responses retain the business idempotency key and reload canonical confirmed plans. */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ApiError,
  messageInput,
  readDraft,
  readConfirmedPlan,
  readWhile,
} from "../src/lib/api.ts";

test("saved plan retry uses persisted plan ID after the first read fails", async () => {
  const original = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = async (input, options) => {
    calls.push(String(input));
    assert.equal(options?.method, "GET");
    return calls.length === 1
      ? Response.json({ message: "暂不可用" }, { status: 503 })
      : Response.json({ plan_id: "saved-id", version: 1 });
  };
  try {
    const identity = { token: "test-token", plan_id: "saved-id" };
    await assert.rejects(
      readConfirmedPlan(identity),
      (error) => error instanceof ApiError && error.status === 503,
    );
    assert.equal((await readConfirmedPlan(identity))?.version, 1);
    assert.deepEqual(calls, ["/api/plans/saved-id", "/api/plans/saved-id"]);
    assert.equal(await readConfirmedPlan({ token: "test-token" }), undefined);
    assert.equal(calls.length, 2);
  } finally {
    globalThis.fetch = original;
  }
});

test("late successful response cannot restore the previous identity or view", async () => {
  let generation = 1;
  const started = generation;
  const read = readWhile(() => generation === started);
  const pending = Promise.withResolvers<string>();
  let identity = "new-session";
  const result = read(pending.promise).then((value) => {
    identity = value;
  });
  generation += 1;
  pending.resolve("old-session");
  await assert.rejects(result, /会话已改变/);
  assert.equal(identity, "new-session");
  assert.equal(
    await readWhile(() => true)(Promise.resolve("current")),
    "current",
  );
});

test("current API failure retains its status for authentication and network recovery", async () => {
  const failure = new ApiError("需要有效身份", 401);
  await assert.rejects(
    readWhile(() => true)(Promise.reject(failure)),
    (error) => error === failure,
  );
});

test("identity change between Promise resolution and view update discards the old view", async () => {
  let generation = 1;
  const started = generation;
  const active = () => generation === started;
  let identity = "current-session";
  const pending = readWhile(active)(Promise.resolve("old-session"));
  const update = pending.then((value) => {
    // 与调用方相同的写回边界：Promise内部检查和外层微任务并非一个原子步骤。
    if (active()) identity = value;
  });
  queueMicrotask(() => {
    generation += 1;
    identity = "new-session";
  });
  await update;
  assert.equal(identity, "new-session");
});

test("pending message survives serialization and explicit retry keeps its ID and mode", () => {
  const first = messageInput(undefined, "京都旅行", "deepseek");
  const restored = JSON.parse(JSON.stringify({ pending_message: first }));
  assert.deepEqual(
    messageInput(restored.pending_message, "京都旅行", "deepseek"),
    first,
  );
  assert.throws(() =>
    messageInput(restored.pending_message, "不同消息", "deepseek"),
  );
  assert.throws(() =>
    messageInput(restored.pending_message, "京都旅行", "offline"),
  );
  assert.notEqual(
    messageInput(undefined, "京都旅行", "deepseek").client_message_id,
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

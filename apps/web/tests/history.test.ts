/** R01/R03: persisted conversation recovery reads pages without generating another run. */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ApiError,
  readRunHistory,
  type HistoricalRun,
} from "../src/lib/api.ts";
import { mergeHistory, mergeRun } from "../src/lib/history.ts";

function run(id: string, sequence = 2): HistoricalRun {
  return {
    run_id: id,
    session_id: "trip",
    created_at: "2026-10-08T00:00:00Z",
    status: "completed",
    mode: "offline",
    answer: `答复${id}`,
    prompt: `消息${id}`,
    error_code: null,
    last_sequence: sequence,
    presentations: [],
  };
}

test("history recovery reads two bounded pages and never submits messages", async () => {
  const original = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = async (input, options) => {
    calls.push(String(input));
    assert.equal(options?.method, "GET");
    return Response.json(
      calls.length === 1
        ? { items: [run("b"), run("c")], next_before: "earlier_cursor" }
        : { items: [run("a"), run("b")], next_before: null },
    );
  };
  try {
    const first = await readRunHistory({
      token: "test-token",
      session_id: "trip",
    });
    const earlier = await readRunHistory(
      { token: "test-token", session_id: "trip" },
      first.next_before ?? undefined,
    );
    const merged = mergeHistory(first.items, earlier.items, "trip");
    assert.deepEqual(
      merged.map((row) => row.run_id),
      ["a", "b", "c"],
    );
    assert.deepEqual(
      merged.map((row) => row.prompt),
      ["消息a", "消息b", "消息c"],
    );
    assert.deepEqual(calls, [
      "/api/sessions/trip/runs?limit=20",
      "/api/sessions/trip/runs?limit=20&before=earlier_cursor",
    ]);
  } finally {
    globalThis.fetch = original;
  }
});

test("late older page cannot roll a completed reply back to running", () => {
  const completed = run("a", 5);
  const old = { ...run("a", 1), status: "running", answer: "" };
  assert.deepEqual(mergeHistory([completed], [old], "trip"), [completed]);
  assert.deepEqual(
    mergeHistory(
      [completed],
      [{ ...completed, answer: "持久化简短说明" }],
      "trip",
    ),
    [completed],
  );
  assert.throws(
    () => mergeHistory([], [{ ...run("x"), session_id: "other" }], "trip"),
    /旅行/,
  );
});

test("history retains API errors so unavailable and unauthorized cannot become empty", async () => {
  const original = globalThis.fetch;
  try {
    for (const status of [401, 404, 503]) {
      globalThis.fetch = async () =>
        Response.json({ message: "无法读取" }, { status });
      await assert.rejects(
        readRunHistory({ token: "test-token", session_id: "trip" }),
        (failure) => failure instanceof ApiError && failure.status === status,
      );
    }
  } finally {
    globalThis.fetch = original;
  }
});

test("refreshing the first page preserves loaded earlier turns and their full replies", () => {
  const earlier = run("a");
  const latest = run("b");
  const page = [{ ...latest, answer: "持久化简短说明" }];
  assert.deepEqual(mergeHistory([earlier, latest], page, "trip"), [
    earlier,
    latest,
  ]);
});

test("latest GET after reply cache expiry preserves full answer but refreshes metadata", () => {
  const current = run("a", 5);
  const persisted = {
    ...current,
    answer: "实时回复仅供本轮查看；行程引用已保存，详情按需更新。",
    status: "partial",
  };
  assert.deepEqual(mergeRun(current, persisted), {
    ...persisted,
    answer: current.answer,
  });
  assert.equal(mergeRun(persisted, current).answer, current.answer);
  assert.deepEqual(mergeRun(current, run("a", 1)), current);
  assert.deepEqual(mergeRun(current, run("b")), run("b"));
});

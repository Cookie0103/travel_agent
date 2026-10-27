/** 连接状态机：EOF 不等于运行结束；终态前断线带游标重连，有上限，取消后保持到终态。 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError } from "../src/lib/api.ts";
import {
  followRun,
  reconnectDelay,
  RECONNECT_LIMIT,
} from "../src/lib/run-stream.ts";

function harness(script: {
  /** 每次 read 前进到的新游标；null 表示这次没有新事件。 */
  reads: (number | null | Error)[];
  statuses: { status: string; last_sequence: number }[];
}) {
  let cursor = 0;
  const afters: number[] = [];
  const waits: number[] = [];
  let read = 0;
  let polled = 0;
  return {
    afters,
    waits,
    options: {
      cursor: () => cursor,
      active: () => true,
      wait: async (ms: number) => void waits.push(ms),
      read: async (after: number) => {
        afters.push(after);
        const step = script.reads[Math.min(read++, script.reads.length - 1)];
        if (step instanceof Error) throw step;
        if (step !== null) cursor = step;
      },
      status: async () =>
        script.statuses[Math.min(polled++, script.statuses.length - 1)],
    },
  };
}

test("stream ending at a terminal status finishes without reconnecting", async () => {
  const h = harness({
    reads: [4],
    statuses: [{ status: "completed", last_sequence: 4 }],
  });
  assert.equal(await followRun(h.options), "terminal");
  assert.deepEqual(h.afters, [0]);
});

test("stream ending while the run is still running reconnects from the max sequence", async () => {
  const h = harness({
    reads: [3, 7],
    statuses: [
      { status: "running", last_sequence: 3 },
      { status: "completed", last_sequence: 7 },
    ],
  });
  assert.equal(await followRun(h.options), "terminal");
  assert.deepEqual(h.afters, [0, 3]);
  assert.equal(h.waits.length, 1);
});

test("a terminal status with unread events is read once more", async () => {
  const h = harness({
    reads: [2, 5],
    statuses: [{ status: "failed", last_sequence: 5 }],
  });
  assert.equal(await followRun(h.options), "terminal");
  assert.deepEqual(h.afters, [0, 2]);
});

test("network errors and 5xx retry with backoff, then give up at the limit", async () => {
  const h = harness({
    reads: [new TypeError("socket hang up")],
    statuses: [{ status: "running", last_sequence: 9 }],
  });
  assert.equal(await followRun(h.options), "exhausted");
  assert.equal(h.afters.length, RECONNECT_LIMIT + 1);
  assert.deepEqual(
    h.waits,
    h.waits.map((_, i) => reconnectDelay(i + 1)),
  );
  assert.ok(h.waits.every((ms, i) => i === 0 || ms >= h.waits[i - 1]));
  assert.ok(Math.max(...h.waits) <= 8000);
});

test("progress resets the failure budget", async () => {
  const reads: (number | null)[] = [];
  for (let i = 1; i <= RECONNECT_LIMIT * 2; i++) reads.push(i);
  const h = harness({
    reads,
    statuses: [
      ...reads.slice(0, -1).map((n) => ({
        status: "running",
        last_sequence: n as number,
      })),
      { status: "completed", last_sequence: reads.length },
    ],
  });
  assert.equal(await followRun(h.options), "terminal");
});

test("auth or missing-run errors are not retried", async () => {
  for (const status of [401, 404]) {
    const h = harness({
      reads: [new ApiError("x", status)],
      statuses: [{ status: "running", last_sequence: 0 }],
    });
    await assert.rejects(followRun(h.options), ApiError);
    assert.equal(h.afters.length, 1);
  }
});

test("after cancel the run stays followed until the terminal status arrives", async () => {
  const h = harness({
    reads: [1, 1, 2],
    statuses: [
      { status: "cancelling", last_sequence: 1 },
      { status: "cancelling", last_sequence: 1 },
      { status: "cancelled", last_sequence: 2 },
    ],
  });
  assert.equal(await followRun(h.options), "terminal");
  assert.deepEqual(h.afters, [0, 1, 1]);
});

test("aborting stops the loop without retrying", async () => {
  const h = harness({
    reads: [null],
    statuses: [{ status: "running", last_sequence: 0 }],
  });
  let live = true;
  const outcome = await followRun({
    ...h.options,
    active: () => live,
    read: async () => {
      live = false;
      throw new DOMException("aborted", "AbortError");
    },
  });
  assert.equal(outcome, "aborted");
});

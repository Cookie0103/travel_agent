/** 运行终态后的记忆抽取轮询：只补新卡，抽取结束或界面离开即停。 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { followMemory } from "../src/lib/run-stream.ts";

type Run = { memory_pending?: boolean | null; presentations?: unknown[] };

async function follow(
  initial: Run,
  statuses: (Run | Error)[],
  active = () => true,
) {
  const hydrated: unknown[] = [];
  let polled = 0;
  await followMemory<Run>({
    initial,
    status: async () => {
      const next = statuses[polled++];
      if (next instanceof Error) throw next;
      return next;
    },
    wait: async () => undefined,
    active,
    hydrate: async (event) => {
      hydrated.push(event);
    },
    limit: 5,
  });
  return { hydrated, polled };
}

test("no pending extraction never polls", async () => {
  const result = await follow(
    { memory_pending: false, presentations: ["a"] },
    [],
  );
  assert.deepEqual(result, { hydrated: [], polled: 0 });
});

test("new cards appended after the run are hydrated once", async () => {
  const result = await follow({ memory_pending: true, presentations: ["a"] }, [
    { memory_pending: true, presentations: ["a"] },
    new Error("network"),
    { memory_pending: false, presentations: ["a", "m1", "m2"] },
  ]);
  assert.deepEqual(result, { hydrated: ["m1", "m2"], polled: 3 });
});

test("stops when the view no longer follows this run and at the poll limit", async () => {
  const left = await follow({ memory_pending: true }, [], () => false);
  assert.equal(left.polled, 0);
  const capped = await follow(
    { memory_pending: true },
    Array.from({ length: 9 }, () => ({
      memory_pending: true,
      presentations: [],
    })),
  );
  assert.equal(capped.polled, 5);
});

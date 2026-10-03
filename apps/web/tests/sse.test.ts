/** The native Node runner verifies UTF-8/chunk boundaries and failure without resubmission. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { readEvents, type AppEvent } from "../src/lib/api.ts";

test("persisted SSE parses fragmented Chinese and resumes from the requested cursor", async () => {
  const original = globalThis.fetch;
  const bytes = new TextEncoder().encode(
    'id: 3\ndata: {"sequence":3,"kind":"text","text":"京都"}\n\n: waiting\n\nid: 4\ndata: {"sequence":4,"kind":"completed"}\n\n',
  );
  let calls = 0;
  globalThis.fetch = async (url, options) => {
    calls++;
    assert.equal(url, "/api/runs/run/events?after=2");
    assert.deepEqual(options?.headers, { Authorization: "Bearer local-test" });
    return new Response(
      new ReadableStream({
        start(controller) {
          for (let index = 0; index < bytes.length; index += 2)
            controller.enqueue(bytes.slice(index, index + 2));
          controller.close();
        },
      }),
    );
  };
  try {
    const events: AppEvent[] = [];
    await readEvents(
      "run",
      "local-test",
      2,
      new AbortController().signal,
      (event) => events.push(event),
    );
    assert.deepEqual(
      events.map((event) => event.sequence),
      [3, 4],
    );
    assert.equal(events[0].text, "京都");
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = original;
  }
});

test("failed or invalid stream reports an error and never posts a new run", async () => {
  const original = globalThis.fetch;
  try {
    for (const response of [
      new Response("denied", { status: 401 }),
      new Response("data: not-json\n\n"),
    ]) {
      let calls = 0;
      globalThis.fetch = async (_url, options) => {
        calls++;
        assert.equal(options?.method, undefined);
        return response;
      };
      await assert.rejects(
        readEvents("run", "test", 0, new AbortController().signal, () => {}),
      );
      assert.equal(calls, 1);
    }
  } finally {
    globalThis.fetch = original;
  }
});

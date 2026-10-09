/** R03: presentation cards and late SSE records belong to a specific trip and turn. */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  belongsToRun,
  runCards,
  hotelsForRun,
} from "../src/lib/early-cards.ts";
import { ApiError, readEvents, type Run, type Hotels } from "../src/lib/api.ts";
const run: Run = {
  session_id: "trip",
  run_id: "draft-turn",
  status: "completed",
  mode: "offline",
  answer: "草稿",
  error_code: null,
  last_sequence: 3,
  created_at: "2026-10-08T00:00:00Z",
  presentations: [],
};
const card = {
  context: { session_id: "trip", run_id: "draft-turn" },
  kind: "presentation",
  presentation: { data: { draft_id: "draft" } },
};

test("old draft belongs only to its producing turn; the following answer has no card", () => {
  assert.deepEqual(runCards({ ...run, presentations: [card] }), {
    draftId: "draft",
  });
  assert.deepEqual(runCards({ ...run, run_id: "query-turn" }), {});
  assert.deepEqual(
    runCards({ ...run, run_id: "query-turn", presentations: [card] }),
    {},
  );
  assert.deepEqual(
    runCards({ ...run, session_id: "another-trip", presentations: [card] }),
    {},
  );
});

test("unknown context and wrong trip/run cannot be accepted as current events", () => {
  assert.equal(belongsToRun(card, run), true);
  assert.equal(belongsToRun({ ...card, context: undefined }, run), false);
  assert.equal(belongsToRun(card, { ...run, run_id: "next" }), false);
  assert.equal(belongsToRun(card, { ...run, session_id: "other" }), false);
});

test("late foreign SSE is dropped without advancing the current turn's cursor", async () => {
  const original = globalThis.fetch;
  const own = { ...card, sequence: 3 };
  globalThis.fetch = async () =>
    new Response(
      `data: ${JSON.stringify({ ...card, sequence: 999, context: { session_id: "other", run_id: "old" } })}\n\ndata: ${JSON.stringify(own)}\n\n`,
    );
  try {
    let cursor = 0;
    const accepted: number[] = [];
    await readEvents(
      run.run_id,
      "synthetic-token",
      0,
      new AbortController().signal,
      (event) => {
        if (!belongsToRun(event, run) || event.sequence <= cursor) return;
        cursor = event.sequence;
        accepted.push(cursor);
      },
    );
    assert.deepEqual(accepted, [3]);
    assert.equal(cursor, 3);
  } finally {
    globalThis.fetch = original;
  }
});

test("unauthorized SSE retains 401 so the owning identity and outbox can be invalidated", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () =>
    Response.json({ message: "需要有效身份" }, { status: 401 });
  try {
    await assert.rejects(
      readEvents(
        "run",
        "synthetic-token",
        0,
        new AbortController().signal,
        () => {},
      ),
      (error) => error instanceof ApiError && error.status === 401,
    );
  } finally {
    globalThis.fetch = original;
  }
});

test("clearing the live hotel cache preserves the producing turn's persisted cards", () => {
  const hotels = { component: "hotel_comparison", cards: [] };
  const comparison = {
    ...run,
    presentations: [{ ...card, presentation: { data: hotels } }],
  };
  assert.deepEqual(hotelsForRun(comparison, undefined, run), hotels);
  assert.equal(
    hotelsForRun({ ...run, run_id: "query-turn" }, undefined, run),
    undefined,
  );
});

test("owned empty/error panel replaces prior success and never inherits another turn's cache", () => {
  const empty: Hotels = {
    component: "hotel_comparison",
    cards: [],
    total_found: null,
    more_url: null,
    more_url_scope: null,
    comparison: {
      room_preferences_question: null,
      budget_relation: null,
      comparable: false,
      lowest_offer_ids: [],
      reasons: ["酒店查询超时"],
      scope: "本轮没有报价",
    },
  };
  const old = { component: "hotel_comparison", cards: [{ offer_id: "old" }] };
  const prior = { ...card, presentation: { data: old } };
  const failure = {
    ...card,
    presentation: { status: "error", error: { code: "timeout" }, data: empty },
  };
  assert.deepEqual(
    runCards({ ...run, presentations: [prior, failure] }).hotels,
    empty,
  );
  const next = {
    ...run,
    run_id: "next",
    presentations: [
      { ...failure, context: { session_id: "trip", run_id: "next" } },
    ],
  };
  assert.deepEqual(hotelsForRun(next, empty, run), empty);
  assert.equal(
    hotelsForRun({ ...next, session_id: "other" }, empty, run),
    undefined,
  );
});

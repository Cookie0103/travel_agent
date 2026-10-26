import assert from "node:assert/strict";
import { test } from "node:test";
import { activityEntries, progressMessage } from "../src/lib/run-progress.ts";
import type { AppEvent } from "../src/lib/api.ts";

function event(sequence: number, kind: string, extra = {}): AppEvent {
  return {
    sequence,
    kind,
    tool_call_id: "hotel-call",
    tool_name: "search_hotel_offers",
    code: null,
    reason: null,
    ...extra,
  } as AppEvent;
}

test("progress follows actual starts and finishes, including time between tools", () => {
  const start = event(1, "tool_started");
  assert.equal(
    progressMessage(activityEntries([start]), "running"),
    "正在比较酒店…",
  );
  const entries = activityEntries([event(2, "tool_finished"), start]);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].type === "tool" && entries[0].state, "ok");
  assert.equal(progressMessage(entries, "running"), "正在整理结果和下一步…");
});

test("repeated names are paired by call id; a later failure never finishes an earlier call", () => {
  const entries = activityEntries([
    event(1, "tool_started"),
    event(2, "tool_started", { tool_call_id: "second" }),
    event(3, "tool_finished", { tool_call_id: "second", code: "timeout" }),
  ]);
  assert.deepEqual(
    entries.map((entry) => entry.type === "tool" && entry.state),
    ["running", "failed"],
  );
  assert.equal(progressMessage(entries, "running"), "正在比较酒店…");
});

test("a finish without its start still appears after the retained event window advances", () => {
  const entries = activityEntries([
    event(81, "tool_finished", { code: "unavailable" }),
  ]);
  assert.equal(entries[0].type === "tool" && entries[0].state, "failed");
});

test("stopping and terminal runs do not claim an unfinished tool is still executing", () => {
  const events = [event(1, "tool_started")];
  assert.equal(
    progressMessage(activityEntries(events), "cancelling"),
    "正在停止本轮处理…",
  );
  for (const status of ["cancelled", "failed", "partial", "completed"]) {
    const entries = activityEntries(events, status);
    assert.equal(entries[0].type === "tool" && entries[0].state, "unknown");
    assert.equal(progressMessage(entries, status), undefined);
  }
});

test("progress contains only labels and closed states, never text or argument values", () => {
  const entries = activityEntries([
    event(1, "tool_started", {
      text: "private",
      arguments: { private: "secret" },
    }),
  ]);
  assert.ok(!JSON.stringify(entries).includes("private"));
  assert.ok(!JSON.stringify(entries).includes("secret"));
});

test("a provisional correction stops claiming ongoing work after any terminal status", () => {
  const events = [
    event(1, "tool_started"),
    event(2, "tool_finished", {
      code: "validation",
      external: { provisional: true },
    }),
  ];
  const pending = activityEntries(events)[0];
  assert.equal(pending.type === "tool" && pending.state, "correcting");
  for (const status of ["cancelled", "failed", "completed"]) {
    const entry = activityEntries(events, status)[0];
    assert.equal(entry.type === "tool" && entry.state, "needs_adjustment");
  }
});

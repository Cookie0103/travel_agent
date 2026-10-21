/** Run steps: de-duplicated ordered rows, server-time elapsed seconds, placement and event cap. */
import assert from "node:assert/strict";
import { test } from "node:test";
import type { AppEvent } from "../src/lib/api.ts";
import {
  EVENT_CAP,
  appendEvent,
  buildSteps,
  elapsedSeconds,
  lineText,
  stepCount,
  stepsPlacement,
  toolLine,
  type ToolStep,
} from "../src/lib/run-steps.ts";

const T0 = Date.parse("2026-10-21T00:00:00Z");
const at = (seconds: number) => new Date(T0 + seconds * 1000).toISOString();
const ctx = { run_id: "r1", session_id: "s1" };
function ev(
  sequence: number,
  kind: string,
  extra: Record<string, unknown> = {},
): AppEvent {
  return {
    sequence,
    kind,
    context: ctx,
    tool_name: null,
    tool_call_id: null,
    code: null,
    reason: null,
    external: null,
    ...extra,
  } as unknown as AppEvent;
}
const start = (seq: number, id: string, name: string, sec?: number) =>
  ev(seq, "tool_started", {
    tool_call_id: id,
    tool_name: name,
    ...(sec === undefined ? {} : { occurred_at: at(sec) }),
  });
const finish = (
  seq: number,
  id: string,
  name: string,
  sec?: number,
  extra: Record<string, unknown> = {},
) =>
  ev(seq, "tool_finished", {
    tool_call_id: id,
    tool_name: name,
    ...(sec === undefined ? {} : { occurred_at: at(sec) }),
    ...extra,
  });
const tools = (steps: ReturnType<typeof buildSteps>) =>
  steps.filter((s): s is ToolStep => s.type === "tool");

test("start then finish gives one ok row with a server duration", () => {
  const steps = tools(
    buildSteps([
      start(1, "a", "search_hotel_offers", 0),
      finish(2, "a", "search_hotel_offers", 3),
    ]),
  );
  assert.equal(steps.length, 1);
  assert.equal(lineText(toolLine(steps[0], T0)), "比较酒店 · 已完成 · 3 秒");
  assert.equal(toolLine(steps[0], T0).mark, "✓");
});

test("a running step ticks from the server start time", () => {
  const [step] = tools(buildSteps([start(1, "a", "estimate_routes", 0)]));
  assert.equal(
    lineText(toolLine(step, T0 + 12_400)),
    "估算路线 · 进行中 · 12 秒",
  );
  assert.equal(toolLine(step, T0 + 12_400).mark, "●");
});

test("clock skew never yields negative seconds", () => {
  assert.equal(elapsedSeconds(T0, T0 - 5000), 0);
  assert.equal(elapsedSeconds(null, T0), null);
});

test("no timestamps: running shows no seconds, finished omits the duration", () => {
  const running = tools(buildSteps([start(1, "a", "estimate_routes")]));
  assert.equal(lineText(toolLine(running[0], T0)), "估算路线 · 进行中");
  const done = tools(
    buildSteps([
      start(1, "a", "estimate_routes"),
      finish(2, "a", "estimate_routes"),
    ]),
  );
  assert.equal(lineText(toolLine(done[0], T0)), "估算路线 · 已完成");
});

test("a sub-second step has no duration suffix", () => {
  const [step] = tools(
    buildSteps([
      start(1, "a", "estimate_routes", 0),
      finish(2, "a", "estimate_routes", 0),
    ]),
  );
  assert.equal(lineText(toolLine(step, T0)), "估算路线 · 已完成");
});

test("failure then successful retry keeps both rows, in order", () => {
  const steps = tools(
    buildSteps([
      start(1, "a", "stage_plan_change", 0),
      finish(2, "a", "stage_plan_change", 1, { code: "validation" }),
      start(3, "b", "stage_plan_change", 2),
      finish(4, "b", "stage_plan_change", 4),
    ]),
  );
  assert.deepEqual(
    steps.map((s) => s.state),
    ["failed", "ok"],
  );
  const failed = lineText(toolLine(steps[0], T0));
  assert.match(failed, /^生成行程草稿 · 失败 — 校验未通过/);
  assert.equal(toolLine(steps[0], T0).mark, "✗");
});

test("finish without start becomes its own row without seconds", () => {
  const steps = tools(buildSteps([finish(5, "x", "search_places", 9)]));
  assert.equal(steps.length, 1);
  assert.equal(steps[0].state, "ok");
  assert.equal(lineText(toolLine(steps[0], T0)), "搜索景点 · 已完成");
});

test("out-of-order sequences are sorted before pairing", () => {
  const steps = tools(
    buildSteps([
      finish(2, "a", "search_places", 2),
      start(1, "a", "search_places", 0),
    ]),
  );
  assert.equal(steps.length, 1);
  assert.equal(lineText(toolLine(steps[0], T0)), "搜索景点 · 已完成 · 2 秒");
});

test("replayed events do not duplicate rows or counts", () => {
  const events = [
    start(1, "a", "search_places", 0),
    finish(2, "a", "search_places", 1),
    start(3, "b", "estimate_routes", 1),
  ];
  const replay = [...events, ...events, start(9, "b", "estimate_routes", 1)];
  assert.equal(tools(buildSteps(replay)).length, 2);
  assert.equal(stepCount(replay), 2);
  assert.equal(stepCount(events), 2);
});

test("unknown tool names are shown as received", () => {
  const [step] = tools(buildSteps([start(1, "a", "brand_new_tool", 0)]));
  assert.equal(lineText(toolLine(step, T0)), "brand_new_tool · 进行中 · 0 秒");
});

test("extra rows for presentation and compaction keep their place", () => {
  const steps = buildSteps([
    start(1, "a", "search_places", 0),
    ev(2, "presentation"),
    ev(3, "context_compacted"),
    finish(4, "a", "search_places", 1),
  ]);
  assert.deepEqual(
    steps.map((s) => s.type),
    ["tool", "presentation", "compacted"],
  );
  assert.equal(stepCount([start(1, "a", "x"), ev(2, "presentation")]), 1);
});

test("provisional failure is a correcting row; settled runs resolve it and open steps", () => {
  const events = [
    start(1, "a", "stage_plan_change", 0),
    finish(2, "a", "stage_plan_change", 1, {
      code: "validation",
      external: { provisional: true },
    }),
    start(3, "b", "search_places", 1),
  ];
  const live = tools(buildSteps(events));
  assert.deepEqual(
    live.map((s) => s.state),
    ["correcting", "running"],
  );
  assert.match(lineText(toolLine(live[0], T0)), /修正参数重试中 — /);
  const settled = tools(buildSteps(events, { settled: true }));
  assert.deepEqual(
    settled.map((s) => s.state),
    ["failed", "interrupted"],
  );
  assert.equal(lineText(toolLine(settled[1], T0)), "搜索景点 · 已中断");
});

test("more than 80 events keep every step", () => {
  let events: AppEvent[] = [];
  for (let i = 0; i < 60; i += 1) {
    events = appendEvent(events, start(i * 3 + 1, `c${i}`, "search_places", i));
    events = appendEvent(events, ev(i * 3 + 2, "presentation"));
    events = appendEvent(
      events,
      finish(i * 3 + 3, `c${i}`, "search_places", i + 1),
    );
  }
  assert.equal(events.length, 180);
  assert.equal(tools(buildSteps(events)).length, 60);
  assert.equal(stepCount(events), 60);
  assert.equal(tools(buildSteps(events))[0].key, "s1");
});

test("appendEvent ignores a replayed sequence and bounds memory", () => {
  const one = appendEvent([], start(1, "a", "search_places"));
  assert.equal(appendEvent(one, start(1, "a", "search_places")).length, 1);
  let events: AppEvent[] = [];
  for (let i = 1; i <= EVENT_CAP + 20; i += 1)
    events = appendEvent(events, ev(i, "presentation"));
  assert.equal(events.length, EVENT_CAP);
  assert.equal(events[0].sequence, 21);
});

test("placement: live while active, folded after an answer, expanded on failure", () => {
  assert.equal(stepsPlacement({ status: "running" }), "live");
  assert.equal(stepsPlacement({ status: "cancelling", answer: "x" }), "live");
  assert.equal(stepsPlacement({ status: "completed", answer: "x" }), "folded");
  assert.equal(stepsPlacement({ status: "partial", answer: "x" }), "folded");
  assert.equal(stepsPlacement({ status: "failed", answer: "x" }), "expanded");
  assert.equal(stepsPlacement({ status: "cancelled" }), "expanded");
  assert.equal(stepsPlacement({ status: "completed" }), "expanded");
  assert.equal(
    stepsPlacement({ status: "completed", answer: "x", guided: true }),
    "expanded",
  );
});

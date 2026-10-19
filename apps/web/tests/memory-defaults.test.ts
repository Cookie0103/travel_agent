import assert from "node:assert/strict";
import { test } from "node:test";
import type { Choice } from "../src/lib/api.ts";
import { memoryPicks } from "../src/lib/choices.ts";
import { memoryLabels, memoryValue } from "../src/lib/memory.ts";

const card = (id: string, def?: string): Choice =>
  ({
    choice_id: id,
    question: id,
    options: [
      { option_id: "remember", label: "记住" },
      { option_id: "once", label: "这次而已" },
    ],
    ...(def ? { default_option_id: def } : {}),
  }) as Choice;

test("merged memory cards preselect their default, user picks win", () => {
  const cards = [card("a", "remember"), card("b", "remember"), card("c")];
  assert.deepEqual(memoryPicks(cards, {}), { a: "remember", b: "remember" });
  assert.deepEqual(memoryPicks(cards, { b: "once" }), {
    a: "remember",
    b: "once",
  });
});

test("unknown default and answered cards are not preselected", () => {
  const answered = { ...card("d", "remember"), answered_option_id: "once" };
  assert.deepEqual(
    memoryPicks([card("e", "nope"), answered as Choice], {}),
    {},
  );
});

test("wake_time and evening_end are labelled; free text shown as-is", () => {
  assert.equal(memoryLabels.wake_time, "平时起床时间");
  assert.equal(memoryLabels.evening_end, "晚上结束时间");
  assert.equal(
    memoryValue({ key: "wake_time", value: "7:30 左右" } as never),
    "7:30 左右",
  );
});

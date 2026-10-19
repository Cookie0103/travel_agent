/** C5: unsaved edits survive refreshes; facts are grouped by what they actually apply to. */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  factGroups,
  factStatus,
  isDirty,
  preferenceLines,
} from "../src/lib/preference-form.ts";
import type { MemoryFact } from "../src/lib/memory.ts";

const fact = (patch: Partial<MemoryFact>) =>
  ({
    fact_id: "f",
    key: "interest",
    value: "寺庙",
    scope: "long_term",
    session_id: null,
    status: "active",
    source: "manual",
    ...patch,
  }) as MemoryFact;

test("lines trims and drops blanks; dirty compares against saved values", () => {
  assert.deepEqual(preferenceLines(" 寺庙 \n\n 美食\n"), ["寺庙", "美食"]);
  const saved = { interests: ["寺庙"], soft_constraints: [], transport: null };
  const form = { interests: "寺庙", constraints: "", transport: null };
  assert.equal(isDirty(saved, form), false);
  assert.equal(isDirty(saved, { ...form, interests: "寺庙\n夜景" }), true);
  assert.equal(isDirty(saved, { ...form, transport: "walk" }), true);
  assert.equal(isDirty(undefined, form), false);
});

test("other sessions' trip facts are neither current nor history, and never labelled active", () => {
  const mine = fact({ fact_id: "a", scope: "trip", session_id: "s1" });
  const other = fact({ fact_id: "b", scope: "trip", session_id: "s2" });
  const longTerm = fact({ fact_id: "c" });
  const old = fact({ fact_id: "d", status: "superseded" });
  const groups = factGroups([mine, other, longTerm, old], "s1");
  assert.deepEqual(
    groups.current.map((f) => f.fact_id),
    ["a", "c"],
  );
  assert.deepEqual(
    groups.elsewhere.map((f) => f.fact_id),
    ["b"],
  );
  assert.deepEqual(
    groups.history.map((f) => f.fact_id),
    ["d"],
  );
  assert.equal(factStatus(other, "s1"), "仅用于其他旅行");
  assert.equal(factStatus(mine, "s1"), "生效");
  assert.equal(factStatus(old, "s1"), "已被取代");
});

import assert from "node:assert/strict";
import { test } from "node:test";
import { sourceLabel, sourceRows } from "../src/lib/condition-source.ts";

test("old, absent, unknown and untrusted sources never claim conversation attribution", () => {
  assert.equal(sourceLabel(undefined, "city"), "");
  assert.equal(sourceLabel({ city: "none" }, "city"), "");
  assert.equal(sourceLabel({ city: "untrusted" }, "city"), "");
  assert.deepEqual(sourceRows(undefined), []);
  assert.deepEqual(sourceRows({ city: "none", budget: "none" }), []);
});

test("summary attributes each known field without filling unknown fields or using another field source", () => {
  const sources = {
    city: "conversation",
    adults: "user_form",
    rooms: "none",
    budget: "conversation",
  };
  assert.equal(sourceLabel(sources, "adults"), "手动填写");
  assert.deepEqual(sourceRows(sources), [
    "目的地 · 来自对话",
    "成人 · 手动填写",
    "全程预算 · 来自对话",
  ]);
});

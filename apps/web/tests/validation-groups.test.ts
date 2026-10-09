import assert from "node:assert/strict";
import { test } from "node:test";
import {
  validationGroups,
  checkTargets,
} from "../src/lib/validation-groups.ts";

const entry = (
  code: string,
  subject: string,
  status: "unknown" | "conflict" | "verified" = "unknown",
) => ({ code, subject, status, message: `${code}:${subject}` });

test("same code and state group with exact counts; conflict stays separate and first", () => {
  const groups = validationGroups([
    entry("opening_hours", "item:0"),
    entry("route_missing", "route:0->1"),
    entry("opening_hours", "item:1"),
    entry("opening_hours", "item:2", "conflict"),
    entry("opening_hours", "item:3", "verified"),
  ]);
  assert.deepEqual(
    groups.map((g) => [g.label, g.status, g.checks.length]),
    [
      ["营业时间", "conflict", 1],
      ["营业时间", "unknown", 2],
      ["路线信息", "unknown", 1],
    ],
  );
  assert.equal(groups[1].checks[1].subject, "item:1");
  assert.deepEqual(
    validationGroups([entry("future_code", "request")]).map((g) => g.label),
    ["其他校验"],
  );
});

const cards = [
  { start: "2026-11-03T15:30:00Z", name: "甲" },
  { start: "2026-11-04T01:00:00Z", name: "乙" },
  { start: "2026-11-05T01:00:00Z", name: "丙" },
];

test("item, directed route and JST day subjects locate exact existing cards", () => {
  assert.deepEqual(checkTargets("item:1", cards), [1]);
  assert.deepEqual(checkTargets("route:0->1", cards), [0, 1]);
  assert.deepEqual(checkTargets("day:2026-11-04", cards), [0, 1]);
});

test("invalid indices, dates and unknown subjects never guess a target", () => {
  for (const subject of [
    "item:3",
    "item:-1",
    "item:1junk",
    "item:1.5",
    "item:01",
    "route:2->3",
    "route:2->1",
    "route:0->2",
    "day:2026-02-31",
    "place:uuid",
    "budget",
    "request",
  ])
    assert.deepEqual(checkTargets(subject, cards), [], subject);
});

test("unknown codes that match Object prototype keys still use the safe label", () => {
  for (const code of ["__proto__", "constructor", "toString"])
    assert.equal(
      validationGroups([entry(code, "request")])[0].label,
      "其他校验",
    );
});

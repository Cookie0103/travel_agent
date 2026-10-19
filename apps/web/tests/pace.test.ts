import assert from "node:assert/strict";
import { test } from "node:test";
import {
  currentPace,
  longTermPace,
  mergePace,
  paceLabel,
  paceLine,
} from "../src/lib/pace.ts";

test("mergePace replaces an existing pace entry and keeps the others", () => {
  assert.deepEqual(mergePace(["少走路", "节奏：慢节奏", "吃抹茶"], "特种兵"), [
    "少走路",
    "吃抹茶",
    "节奏：特种兵",
  ]);
});

test("mergePace adds the entry when none exists", () => {
  assert.deepEqual(mergePace([], "标准"), ["节奏：标准"]);
});

test("currentPace leaves missing or unknown pace unset", () => {
  assert.equal(currentPace(["节奏：特种兵"]), "特种兵");
  assert.equal(currentPace(["节奏：疯狂"]), "");
  assert.equal(currentPace([]), "");
});

test("mergePace preserves an unchanged pace position and removes duplicate pace entries", () => {
  assert.deepEqual(mergePace(["节奏：慢节奏", "少走路"], "慢节奏"), [
    "节奏：慢节奏",
    "少走路",
  ]);
  assert.deepEqual(
    mergePace(["少走路", "节奏：标准", "节奏：慢节奏"], "特种兵"),
    ["少走路", "节奏：特种兵"],
  );
});

test("pace aliases and confirmed hard pace use the same canonical values", () => {
  assert.equal(currentPace(["轻松"]), "慢节奏");
  const withHard = currentPace as unknown as (
    soft: string[],
    hard: string[],
  ) => string;
  assert.equal(withHard(["节奏：标准"], ["佛系"]), "慢节奏");
  assert.deepEqual(mergePace(["悠闲", "少走路"], "标准"), [
    "少走路",
    "节奏：标准",
  ]);
});

test("prototype names remain unrelated free constraints", () => {
  for (const name of ["constructor", "toString", "__proto__"]) {
    assert.equal(currentPace([name]), "");
    assert.equal(currentPace([], [name]), "");
    assert.deepEqual(mergePace([name], "标准"), [name, "节奏：标准"]);
  }
});

test("paceLabel shows the stated pace plainly and marks the unset default as an assumption", () => {
  assert.equal(paceLabel("慢节奏"), "节奏：慢节奏");
  assert.equal(paceLabel(""), "节奏：标准（默认假设，未指定）");
});

test("the pace line names where the pace came from", () => {
  assert.equal(paceLine("特种兵", ""), "节奏：特种兵（本次指定）");
  assert.equal(paceLine("特种兵", "慢节奏"), "节奏：特种兵（本次指定）");
  assert.equal(paceLine("", "慢节奏"), "节奏：慢节奏（长期偏好）");
  assert.equal(paceLine("", ""), "节奏：标准（默认假设，未指定）");
});

test("only an active long-term pace fact counts as a long-term preference", () => {
  const fact = (over: object) => ({
    key: "pace",
    value: "慢节奏",
    scope: "long_term",
    status: "active",
    created_at: "2026-10-01T00:00:00Z",
    ...over,
  });
  const facts = (list: object[]) => list as Parameters<typeof longTermPace>[0];
  assert.equal(longTermPace(facts([fact({})])), "慢节奏");
  assert.equal(longTermPace(facts([fact({ scope: "trip" })])), "");
  assert.equal(longTermPace(facts([fact({ status: "proposed" })])), "");
  assert.equal(longTermPace(facts([fact({ status: "deleted" })])), "");
  assert.equal(longTermPace(facts([fact({ value: null })])), "");
  assert.equal(longTermPace(facts([fact({ key: "transport" })])), "");
  assert.equal(
    longTermPace(
      facts([
        fact({ value: "标准" }),
        fact({ value: "特种兵", created_at: "2026-10-05T00:00:00Z" }),
      ]),
    ),
    "特种兵",
    "newest wins",
  );
  assert.equal(longTermPace([]), "");
});

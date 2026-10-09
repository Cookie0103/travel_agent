import assert from "node:assert/strict";
import { test } from "node:test";
import { currentPace, mergePace } from "../src/lib/pace.ts";

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

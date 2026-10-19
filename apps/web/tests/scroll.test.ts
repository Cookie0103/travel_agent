/** Sticky-bottom scrolling follows new content only while the reader is near the end. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { isNearBottom } from "../src/lib/scroll.ts";

const box = (scrollTop: number) => ({
  scrollTop,
  clientHeight: 500,
  scrollHeight: 2000,
});

test("at or near the bottom counts as following", () => {
  assert.equal(isNearBottom(box(1500)), true);
  assert.equal(isNearBottom(box(1450)), true);
});

test("scrolled up beyond the threshold is reading history", () => {
  assert.equal(isNearBottom(box(1000)), false);
  assert.equal(isNearBottom(box(1399)), false);
});

test("content shorter than the viewport is always at the bottom", () => {
  assert.equal(
    isNearBottom({ scrollTop: 0, clientHeight: 500, scrollHeight: 300 }),
    true,
  );
});

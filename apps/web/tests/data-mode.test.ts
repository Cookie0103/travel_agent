import assert from "node:assert/strict";
import test from "node:test";
import { sourceLabel } from "../src/lib/data-mode.ts";

test("synthetic cards are explicitly test data and never called live", () => {
  assert.equal(sourceLabel("synthetic"), "测试数据，不是真实酒店/地点");
  assert.equal(sourceLabel("live"), "乐天实时");
  assert.equal(sourceLabel("fixture"), "模拟报价");
  assert.equal(sourceLabel("snapshot"), "历史快照");
});

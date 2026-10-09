import assert from "node:assert/strict";
import { test } from "node:test";
import { workspaceTab } from "../src/lib/workspace-tabs.ts";

test("workspace tabs wrap arrow keys and support Home/End", () => {
  assert.equal(workspaceTab("ArrowRight", "chat"), "trip");
  assert.equal(workspaceTab("ArrowLeft", "trip"), "chat");
  assert.equal(workspaceTab("ArrowRight", "trip"), "chat");
  assert.equal(workspaceTab("ArrowLeft", "chat"), "trip");
  assert.equal(workspaceTab("Home", "trip"), "chat");
  assert.equal(workspaceTab("End", "chat"), "trip");
  assert.equal(workspaceTab("Tab", "chat"), undefined);
  assert.equal(workspaceTab("Enter", "trip"), undefined);
});

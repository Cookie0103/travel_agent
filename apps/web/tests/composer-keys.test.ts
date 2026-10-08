/** Enter-to-send must not fire during IME composition or with Shift. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { shouldSubmitOnEnter } from "../src/lib/composer-keys.ts";

const key = { key: "Enter", shiftKey: false, isComposing: false, keyCode: 13 };

test("plain Enter submits when sending is allowed", () => {
  assert.equal(shouldSubmitOnEnter(key, true), true);
});

test("Shift+Enter, IME composition, keyCode 229, other keys and blocked state do not submit", () => {
  assert.equal(shouldSubmitOnEnter({ ...key, shiftKey: true }, true), false);
  assert.equal(shouldSubmitOnEnter({ ...key, isComposing: true }, true), false);
  assert.equal(shouldSubmitOnEnter({ ...key, keyCode: 229 }, true), false);
  assert.equal(shouldSubmitOnEnter({ ...key, key: "a" }, true), false);
  assert.equal(shouldSubmitOnEnter(key, false), false);
});

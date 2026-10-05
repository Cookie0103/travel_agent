/** Early card hydration is triggered only by presentation events that carry data. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { isCardEvent } from "../src/lib/early-cards.ts";

test("presentation event with data triggers early hydration", () => {
  assert.equal(
    isCardEvent({
      kind: "presentation",
      presentation: { data: { draft_id: "d" } },
    }),
    true,
  );
});

test("other kinds, missing or empty payloads do not trigger", () => {
  assert.equal(isCardEvent({ kind: "tool_finished" }), false);
  assert.equal(isCardEvent({ kind: "presentation" }), false);
  assert.equal(isCardEvent({ kind: "presentation", presentation: {} }), false);
  assert.equal(
    isCardEvent({ kind: "tool_finished", presentation: { data: {} } }),
    false,
  );
});

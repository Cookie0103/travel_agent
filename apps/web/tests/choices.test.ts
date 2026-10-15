import assert from "node:assert/strict";
import { test } from "node:test";
import { messageInput, type Choice } from "../src/lib/api.ts";
import { choiceDisabled, choiceMessage } from "../src/lib/choices.ts";
import { historicalChoiceEvents } from "../src/lib/early-cards.ts";
import type { Run } from "../src/lib/api.ts";

const card: Choice = {
  choice_id: "c",
  kind: "pace",
  session_id: "s",
  source_run_id: "r",
  expected_revision: 1,
  question: "旅行节奏",
  created_at: "2026-10-13T00:00:00Z",
  options: [
    { option_id: "standard", label: "标准", value: "标准" },
    { option_id: "intensive", label: "特种兵", value: "特种兵" },
    { option_id: "relaxed", label: "比较轻松", value: "慢节奏" },
  ],
  expires_at: null,
  answered_option_id: null,
  stale: false,
};
test("three server options create a structured choice without typed feedback", () => {
  assert.deepEqual(
    card.options.map((o) => o.label),
    ["标准", "特种兵", "比较轻松"],
  );
  const selection = choiceMessage(card, "relaxed");
  const body = messageInput(undefined, "选择比较轻松", "offline", selection);
  assert.deepEqual(body.selection, { choice_id: "c", option_id: "relaxed" });
  assert.equal(body.expected_revision, 1);
  assert.equal(body.hotel_stays, undefined);
  assert.equal(messageInput(body, body.text, "offline", selection), body);
  assert.throws(() =>
    messageInput(body, body.text, "offline", choiceMessage(card, "standard")),
  );
});
test("busy, answered, stale and expired cards cannot submit", () => {
  assert.equal(choiceDisabled(card, false, "s", 1), false);
  assert.equal(choiceDisabled(card, true, "s", 1), true);
  assert.equal(choiceDisabled(card, false, "another-trip", 1), true);
  assert.equal(choiceDisabled(card, false, "s", 2), true);
  assert.equal(
    choiceDisabled({ ...card, answered_option_id: "relaxed" }, false, "s", 1),
    true,
  );
  assert.equal(choiceDisabled({ ...card, stale: true }, false, "s", 1), true);
  assert.equal(
    choiceDisabled(
      { ...card, expires_at: "2000-01-01T00:00:00Z" },
      false,
      "s",
      1,
    ),
    true,
  );
  assert.throws(() => choiceMessage(card, "invented"));
});

test("an answered source card is rehydrated when the latest reply has no choice", () => {
  const source: Run = {
    run_id: "r",
    session_id: "s",
    status: "completed",
    mode: "offline",
    answer: "请选择",
    error_code: null,
    last_sequence: 2,
    created_at: "2026-10-13T00:00:00Z",
    presentations: [
      {
        context: { run_id: "r", session_id: "s" },
        presentation: { data: { component: "choice", ...card } },
      },
      {
        context: { run_id: "r", session_id: "s" },
        presentation: { data: { component: "itinerary", draft_id: "d" } },
      },
    ],
  };
  const latest = {
    ...source,
    run_id: "ordinary",
    answer: "普通回复",
    presentations: [],
  };
  const restore = historicalChoiceEvents([source, latest]);
  assert.equal(restore.length, 1);
  assert.equal(restore[0].run.run_id, "r");
  assert.equal(
    historicalChoiceEvents([{ ...source, session_id: "other" }]).length,
    0,
  );
});

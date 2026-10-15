import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { messageInput, type Choice } from "../src/lib/api.ts";
import {
  answersSummary,
  choiceDisabled,
  choiceMessage,
  validAnswers,
} from "../src/lib/choices.ts";

const base = {
  choice_id: "c",
  session_id: "s",
  source_run_id: "r",
  expected_revision: 1,
  question: "确认出行安排",
  created_at: "2026-10-15T00:00:00Z",
  options: [{ option_id: "confirm", label: "确认并继续", value: "confirm" }],
  expires_at: null,
  answered_option_id: null,
  stale: false,
};
// Cast until generated types include kind "form" and card.form.
const form = {
  ...base,
  kind: "form",
  form: {
    groups: [
      {
        key: "transport",
        label: "交通",
        kind: "choice",
        multi: false,
        required: true,
        options: [
          { option_id: "walk", label: "步行" },
          { option_id: "transit", label: "公共交通" },
        ],
      },
      {
        key: "interests",
        label: "兴趣",
        kind: "choice",
        multi: true,
        required: false,
        options: [
          { option_id: "food", label: "美食" },
          { option_id: "temple", label: "寺庙" },
        ],
      },
      {
        key: "times",
        label: "抵达／离开时间对吗？",
        kind: "times",
        multi: false,
        required: true,
        options: [],
        shown: ["10/20 09:00抵达", "10/22 22:00离开"],
      },
    ],
  },
} as unknown as Choice;
const ok = { transport: ["transit"], times: ["yes"] };

test("answers are validated only against the card's own groups", () => {
  assert.ok(validAnswers(form, ok));
  assert.ok(validAnswers(form, { ...ok, interests: ["food", "temple"] }));
  assert.ok(!validAnswers(form, { times: ["yes"] }), "required missing");
  assert.ok(!validAnswers(form, { ...ok, transport: ["taxi"] }), "foreign");
  assert.ok(!validAnswers(form, { ...ok, transport: ["walk", "transit"] }));
  assert.ok(!validAnswers(form, { ...ok, interests: ["food", "food"] }));
  assert.ok(!validAnswers(form, { ...ok, extra: ["x"] }), "unknown key");
  assert.ok(!validAnswers(form, { transport: ["walk"] }), "times unresolved");
  assert.ok(!validAnswers(form, { ...ok, times: ["maybe"] }));
  assert.ok(!validAnswers(form, { ...ok, times_corrected: ["x", "y"] }));
});

test("a rejected times answer needs one non-empty correction per shown item", () => {
  const no = { transport: ["walk"], times: ["no"] };
  const fixed = ["10/20 10:00抵达", "10/22 21:00离开"];
  assert.ok(validAnswers(form, { ...no, times_corrected: fixed }));
  assert.ok(!validAnswers(form, no));
  assert.ok(!validAnswers(form, { ...no, times_corrected: [fixed[0]] }));
  assert.ok(!validAnswers(form, { ...no, times_corrected: [fixed[0], "  "] }));
  assert.ok(
    !validAnswers(form, {
      ...no,
      times_corrected: [fixed[0], "x".repeat(201)],
    }),
  );
});

test("a form is submitted once as one structured selection", () => {
  const selection = choiceMessage(form, "confirm", ok);
  assert.deepEqual(selection.selection, {
    choice_id: "c",
    option_id: "confirm",
    answers: ok,
  });
  const body = messageInput(undefined, "确认", "offline", selection);
  assert.equal(messageInput(body, body.text, "offline", selection), body);
  assert.throws(() => choiceMessage(form, "confirm"));
  assert.throws(() => choiceMessage(form, "confirm", { times: ["yes"] }));
  assert.match(answersSummary(form, ok), /交通：公共交通/);
});

test("disabled, stale and answered forms cannot submit", () => {
  assert.equal(choiceDisabled(form, false, "s", 1), false);
  assert.equal(choiceDisabled(form, true, "s", 1), true);
  assert.equal(choiceDisabled(form, false, "s", 2), true);
  assert.equal(choiceDisabled({ ...form, stale: true }, false, "s", 1), true);
  assert.equal(
    choiceDisabled({ ...form, answered_option_id: "confirm" }, false, "s", 1),
    true,
  );
});

test("the hotel selection message keeps the plan and only adjusts the ends", () => {
  const source = readFileSync("src/components/conversation.tsx", "utf8");
  assert.match(source, /请保留已有景点和顺序，只按它调整首尾行程和时间/);
  assert.doesNotMatch(source, /每天结束于酒店/);
});

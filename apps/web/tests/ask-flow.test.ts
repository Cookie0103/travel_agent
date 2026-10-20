import assert from "node:assert/strict";
import { test } from "node:test";
import { messageInput, type Choice, type Hotels } from "../src/lib/api.ts";
import {
  answersSummary,
  assignOf,
  choiceMessage,
  cleanAnswers,
  selectionText,
  setGroupOption,
  setGroupText,
  validAnswers,
  type FormGroup,
} from "../src/lib/choices.ts";
import {
  effectiveChoices,
  emptyHotelNotice,
  skipHotelsMessage,
  type HotelSelectionView,
} from "../src/lib/hotel-flow.ts";
import { segmentHotelRows } from "../src/lib/hotel-groups.ts";
import { pendingFor, persistIdentity } from "../src/lib/identity-storage.ts";

const base = {
  choice_id: "c",
  session_id: "s",
  source_run_id: "r",
  expected_revision: 5,
  question: "请一次确认以下信息，再继续",
  created_at: "2026-10-19T00:00:00Z",
  options: [{ option_id: "confirm", label: "确认并继续", value: "confirm" }],
  expires_at: null,
  answered_option_id: null,
  stale: false,
};
const wake = {
  key: "wake",
  label: "平时几点起床",
  kind: "choice",
  multi: false,
  required: false,
  allow_text: true,
  text_kind: "time",
  placeholder: "如 7:30",
  options: [
    { option_id: "w0630", label: "6:30 左右" },
    { option_id: "any", label: "不确定" },
  ],
} as unknown as FormGroup;
const pace = {
  key: "pace",
  label: "旅行节奏",
  kind: "choice",
  multi: false,
  required: false,
  options: [
    { option_id: "relaxed", label: "轻松" },
    { option_id: "any", label: "无要求/不确定" },
  ],
} as unknown as FormGroup;
const ask = {
  ...base,
  kind: "form",
  form: { purpose: "trip_ask", groups: [pace, wake] },
} as unknown as Choice;

test("option and text are mutually exclusive inside one group", () => {
  let answers = setGroupOption({}, wake, "w0630");
  assert.deepEqual(answers, { wake: ["w0630"] });
  answers = setGroupText(answers, wake, "7:30");
  assert.deepEqual(answers, { wake_text: ["7:30"] });
  answers = setGroupOption(answers, wake, "any");
  assert.deepEqual(answers, { wake: ["any"] });
  assert.deepEqual(setGroupOption(answers, wake, "any"), {}, "toggle off");
  assert.deepEqual(setGroupText({ wake: ["any"] }, wake, ""), {});
  assert.deepEqual(setGroupText({}, pace, "x"), {}, "no text on plain groups");
});

test("a trip_ask card confirms with zero answers; text answers are validated", () => {
  assert.ok(validAnswers(ask, {}));
  assert.ok(validAnswers(ask, { pace: ["any"], wake_text: ["看情况"] }));
  assert.ok(
    !validAnswers(ask, { wake: ["w0630"], wake_text: ["7:30"] }),
    "both",
  );
  assert.ok(!validAnswers(ask, { pace_text: ["x"] }), "text on non-text group");
  assert.ok(!validAnswers(ask, { wake_text: ["  "] }));
  assert.ok(!validAnswers(ask, { wake_text: ["x".repeat(41)] }));
  assert.ok(!validAnswers(ask, { wake_text: ["a", "b"] }));
  assert.ok(!validAnswers(ask, { wake: ["nope"] }));
  const generic = { ...ask, form: { groups: [pace] } } as unknown as Choice;
  assert.ok(!validAnswers(generic, {}), "ordinary forms still need one answer");
});

test("cleanAnswers trims text and drops blank text", () => {
  assert.deepEqual(cleanAnswers({ wake_text: [" 7:30 "] }), {
    wake_text: ["7:30"],
  });
  assert.deepEqual(cleanAnswers({ wake_text: ["  "], pace: ["any"] }), {
    pace: ["any"],
  });
});

test("the echo lists only answered groups, text included; empty is explicit", () => {
  assert.equal(
    answersSummary(ask, { pace: ["any"], wake_text: ["7:30"] }),
    "确认：旅行节奏：无要求/不确定；平时几点起床：7:30。",
  );
  assert.equal(answersSummary(ask, {}), "确认出行信息");
  const body = choiceMessage(ask, "confirm", { wake_text: ["7:30"] });
  assert.deepEqual(body.selection.answers, { wake_text: ["7:30"] });
  assert.ok(choiceMessage(ask, "confirm", {}));
});

const assign = {
  ...base,
  kind: "hotel_assign",
  question: "因为你没说，已自动归到京都的住宿段，可以吗？",
  options: [
    { option_id: "confirm", label: "确认", value: "confirm" },
    { option_id: "deny", label: "否", value: "deny" },
  ],
  assign: {
    hotel_name: "某酒店",
    city: "京都",
    check_in: "2026-11-20",
    check_out: "2026-11-22",
    needs_city: false,
  },
} as unknown as Choice;

test("hotel_assign: deny must carry a city, the others never carry answers", () => {
  assert.equal(assignOf(assign)?.hotel_name, "某酒店");
  assert.equal(assignOf(ask), null);
  assert.deepEqual(choiceMessage(assign, "confirm").selection, {
    choice_id: "c",
    option_id: "confirm",
  });
  assert.deepEqual(
    choiceMessage(assign, "deny", { city: ["大阪"] }).selection.answers,
    { city: ["大阪"] },
  );
  assert.throws(() => choiceMessage(assign, "deny"));
  assert.throws(() => choiceMessage(assign, "deny", { city: ["  "] }));
  assert.throws(() =>
    choiceMessage(assign, "deny", { city: ["x".repeat(41)] }),
  );
  assert.throws(() => choiceMessage(assign, "confirm", { city: ["大阪"] }));
  assert.equal(selectionText(assign, "confirm"), "用户选择：确认");
  assert.match(selectionText(assign, "deny", { city: ["大阪"] }), /大阪/);
});

test("skip message is a structured skip bound to the revision", () => {
  const skip = skipHotelsMessage(5);
  assert.deepEqual(skip, {
    expected_revision: 5,
    skip_hotels: true,
    text: "先不选酒店，先排行程",
  });
  const body = messageInput(undefined, skip.text, "offline", skip);
  assert.equal(body.skip_hotels, true);
  assert.equal(body.expected_revision, 5);
  assert.equal(body.hotel_stays, undefined);
  assert.equal(messageInput(body, skip.text, "offline", skip), body);
  assert.throws(() =>
    messageInput(body, skip.text, "offline", skipHotelsMessage(6)),
  );
});

test("an unresolved skip survives a reload", () => {
  const store = new Map<string, string>();
  const mem = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    get length() {
      return store.size;
    },
    key: (i: number) => [...store.keys()][i] ?? null,
  };
  const skip = skipHotelsMessage(5);
  const identity = {
    token: "t",
    session_id: "s",
    pending_message: messageInput(undefined, skip.text, "offline", skip),
  };
  persistIdentity(mem, mem, identity);
  assert.deepEqual(pendingFor(mem, identity), identity.pending_message);
});

type Card = Hotels["cards"][number];
const cards = Array.from(
  { length: 6 },
  (_, i) =>
    ({
      hotel_id: `h${i}`,
      hotel_name: `酒店${i}`,
      offer_id: `o${i}`,
      evidence_id: `e${i}`,
    }) as Card,
);
const comparison = {
  comparable: false,
  lowest_offer_ids: [],
  reasons: [],
  scope: "京都",
  room_preferences_question: null,
  budget_relation: null,
};
const hotels = {
  component: "hotel_comparison",
  comparison: { ...comparison, search_url: "https://travel.rakuten.co.jp/" },
  total_found: null,
  more_url: null,
  more_url_scope: null,
  cards,
  segments: [
    {
      city: "京都",
      check_in: "2026-11-20",
      check_out: "2026-11-22",
      evidence_ids: cards.map((c) => c.evidence_id),
      comparison,
      total_found: 6,
      more_url: null,
      more_url_scope: null,
    },
  ],
} as unknown as Hotels;

test("a single-city segment shows every candidate, never truncated", () => {
  assert.equal(segmentHotelRows(hotels)[0].cards.length, 6);
});

test("server picks count as selected unless the user picked again locally", () => {
  const rows = segmentHotelRows(hotels);
  const pick = { evidence_id: "e2", hotel_name: "酒店2", source: "chat" };
  const view = {
    state: "awaiting",
    can_skip: true,
    segments: [
      {
        city: "京都",
        check_in: "2026-11-20",
        check_out: "2026-11-22",
        selected: pick,
      },
    ],
  } as unknown as HotelSelectionView;
  assert.deepEqual(effectiveChoices(rows, {}, view), { "2026-11-20": "e2" });
  assert.deepEqual(effectiveChoices(rows, { "2026-11-20": "e4" }, view), {
    "2026-11-20": "e4",
  });
  assert.deepEqual(effectiveChoices(rows, {}, undefined), {});
  const gone = {
    ...view,
    segments: [
      { ...view.segments[0], selected: { ...pick, evidence_id: "zz" } },
    ],
  } as unknown as HotelSelectionView;
  assert.deepEqual(effectiveChoices(rows, {}, gone), {}, "unknown evidence");
});

test("no candidates: honest message, Rakuten link and paste hint", () => {
  const empty = { ...hotels, cards: [], segments: undefined } as Hotels;
  const notice = emptyHotelNotice(empty);
  assert.ok(notice);
  assert.match(notice.message, /没有找到/);
  assert.match(notice.hint, /乐天/);
  assert.equal(notice.href, "https://travel.rakuten.co.jp/");
  assert.equal(emptyHotelNotice(hotels), null);
  assert.equal(
    emptyHotelNotice({
      ...empty,
      comparison: { ...empty.comparison, search_url: "http://x" },
    })?.href,
    undefined,
    "only https links",
  );
});

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  hotelPlanSelection,
  type HotelSelectionView,
} from "../src/lib/hotel-flow.ts";

const FUTURE = "2099-01-01T00:00:00Z";
const card = (id: string, name: string, revision = 3, expires = FUTURE) => ({
  evidence_id: id,
  hotel_name: name,
  request_revision: revision,
  expires_at: expires,
});
const rows = [
  {
    city: "京都",
    check_in: "2026-11-20",
    check_out: "2026-11-22",
    cards: [card("k1", "京都A"), card("k2", "京都B")],
  },
  {
    city: "大阪",
    check_in: "2026-11-22",
    check_out: "2026-11-24",
    cards: [card("o1", "大阪A"), card("o2", "大阪B")],
  },
] as unknown as Parameters<typeof hotelPlanSelection>[0];
const view = (picked: Record<string, [string, string] | null>) =>
  ({
    state: "awaiting",
    can_skip: true,
    segments: [
      ["京都", "2026-11-20", "2026-11-22"],
      ["大阪", "2026-11-22", "2026-11-24"],
    ].map(([city, check_in, check_out]) => ({
      city,
      check_in,
      check_out,
      selected: picked[check_in]
        ? {
            evidence_id: picked[check_in]![0],
            hotel_name: picked[check_in]![1],
            source: "chat",
          }
        : null,
    })),
  }) as unknown as HotelSelectionView;
const now = Date.parse("2026-10-19T00:00:00Z");
const plan = (
  local: Record<string, string>,
  v: HotelSelectionView | undefined,
  revision: number | undefined = 3,
) => hotelPlanSelection(rows, local, v, revision, now);

test("server-only picks cover every segment and enable the button", () => {
  const r = plan(
    {},
    view({ "2026-11-20": ["k1", "京都A"], "2026-11-22": ["o2", "大阪B"] }),
  );
  assert.equal(r.reason, undefined);
  assert.deepEqual(r.selection?.hotel_stays, [
    {
      check_in: "2026-11-20",
      check_out: "2026-11-22",
      hotel_evidence_id: "k1",
    },
    {
      check_in: "2026-11-22",
      check_out: "2026-11-24",
      hotel_evidence_id: "o2",
    },
  ]);
  assert.match(r.selection!.text, /大阪B/);
});

test("local-only picks work without a server view", () => {
  const r = plan({ "2026-11-20": "k2", "2026-11-22": "o1" }, undefined);
  assert.deepEqual(
    r.selection?.hotel_stays.map((s) => s.hotel_evidence_id),
    ["k2", "o1"],
  );
});

test("mixed: Osaka from chat (server), Kyoto clicked locally", () => {
  const r = plan(
    { "2026-11-20": "k1" },
    view({ "2026-11-22": ["o1", "大阪A"] }),
  );
  assert.deepEqual(
    r.selection?.hotel_stays.map((s) => s.hotel_evidence_id),
    ["k1", "o1"],
  );
});

test("local pick overrides the server pick for the same segment", () => {
  const r = plan(
    { "2026-11-22": "o2" },
    view({ "2026-11-20": ["k1", "京都A"], "2026-11-22": ["o1", "大阪A"] }),
  );
  assert.deepEqual(
    r.selection?.hotel_stays.map((s) => s.hotel_evidence_id),
    ["k1", "o2"],
  );
  assert.match(r.selection!.text, /大阪B/);
});

test("server pick not among displayed cards still builds a stay", () => {
  const r = plan(
    { "2026-11-20": "k1" },
    view({ "2026-11-22": ["gone", "不在列表的酒店"] }),
  );
  assert.equal(r.selection?.hotel_stays[1].hotel_evidence_id, "gone");
  assert.match(r.selection!.text, /不在列表的酒店/);
});

test("a missing segment keeps the button disabled", () => {
  const r = plan({ "2026-11-20": "k1" }, view({}));
  assert.equal(r.selection, undefined);
});

test("unusable server pick gives the click-again reason", () => {
  const bad = view({
    "2026-11-20": ["k1", "京都A"],
    "2026-11-22": ["", "大阪A"],
  });
  const r = plan({}, bad);
  assert.equal(r.selection, undefined);
  assert.equal(r.reason, "请再点一次该酒店的“选用此酒店”");
});

test("stale local card is rejected", () => {
  const r = plan({ "2026-11-20": "k1", "2026-11-22": "o1" }, undefined, 4);
  assert.equal(r.selection, undefined);
});

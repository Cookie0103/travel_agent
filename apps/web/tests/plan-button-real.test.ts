import assert from "node:assert/strict";
import { test } from "node:test";
import {
  hotelPlanSelection,
  type HotelSelectionView,
} from "../src/lib/hotel-flow.ts";
import { segmentHotelRows } from "../src/lib/hotel-groups.ts";
import type { Hotels } from "../src/lib/api.ts";

const REAL_VIEW = {
  state: "awaiting",
  segments: [
    {
      city: "京都",
      check_in: "2026-11-20",
      check_out: "2026-11-22",
      selected: null,
    },
    {
      city: "大阪",
      check_in: "2026-11-22",
      check_out: "2026-11-23",
      selected: {
        evidence_id: "f7676c38-8053-4294-a36f-9b84392e59e1",
        hotel_name:
          "天然温泉　浪華の湯　ドーミーイン大阪谷町（ドーミーイン・御宿野乃　ホテルズグループ）",
        source: "assign_confirm",
      },
    },
  ],
  can_skip: true,
} as unknown as HotelSelectionView;
const offer = (id: string, hid: string, name: string) => ({
  evidence_id: id,
  offer_id: "o-" + id,
  hotel_id: hid,
  hotel_name: name,
  request_revision: 5,
  expires_at: "2099-01-01T00:00:00.123456+00:00",
});
const cmp = { scope: "x", search_url: null };
const hotels = {
  component: "hotel_comparison",
  cards: [
    offer("k-1", "H1", "京都A"),
    offer("k-2", "H1", "京都A"),
    offer("k-3", "H2", "京都B"),
    offer("f7676c38-8053-4294-a36f-9b84392e59e1", "H3", "ドーミーイン大阪谷町"),
    offer("o-2", "H4", "大阪B"),
  ],
  segments: [
    {
      city: "京都",
      check_in: "2026-11-20",
      check_out: "2026-11-22",
      evidence_ids: ["k-1", "k-2", "k-3"],
      comparison: cmp,
      total_found: 3,
      more_url: null,
      more_url_scope: null,
    },
    {
      city: "大阪",
      check_in: "2026-11-22",
      check_out: "2026-11-23",
      evidence_ids: ["f7676c38-8053-4294-a36f-9b84392e59e1", "o-2"],
      comparison: cmp,
      total_found: 2,
      more_url: null,
      more_url_scope: null,
    },
  ],
  comparison: cmp,
  total_found: 5,
  more_url: null,
  more_url_scope: null,
} as unknown as Hotels;

test("real shapes: Osaka from server, Kyoto clicked locally", () => {
  const rows = segmentHotelRows(hotels);
  const r = hotelPlanSelection(
    rows,
    { "2026-11-20": "k-3" },
    REAL_VIEW,
    5,
    Date.parse("2026-10-19T00:00:00Z"),
  );
  assert.equal(r.reason, undefined);
  assert.deepEqual(r.selection?.hotel_stays, [
    {
      check_in: "2026-11-20",
      check_out: "2026-11-22",
      hotel_evidence_id: "k-3",
    },
    {
      check_in: "2026-11-22",
      check_out: "2026-11-23",
      hotel_evidence_id: "f7676c38-8053-4294-a36f-9b84392e59e1",
    },
  ]);
});

import { planBlockedReason } from "../src/lib/hotel-flow.ts";
const NOW = Date.parse("2026-10-19T00:00:00Z");

test("server pick named differently from any card still enables (no name matching)", () => {
  const rows = segmentHotelRows(hotels);
  const r = hotelPlanSelection(
    rows,
    { "2026-11-20": "k-1" },
    REAL_VIEW,
    5,
    NOW,
  );
  assert.ok(r.selection);
  assert.match(r.selection.text, /浪華の湯/);
});

test("stale or expired local Kyoto card gives an accurate reason", () => {
  const rows = segmentHotelRows(hotels);
  const stale = hotelPlanSelection(
    rows,
    { "2026-11-20": "k-3" },
    REAL_VIEW,
    6,
    NOW,
  );
  assert.equal(stale.selection, undefined);
  assert.match(stale.reason!, /旧条件/);
  const expired = hotelPlanSelection(
    rows,
    { "2026-11-20": "k-3" },
    REAL_VIEW,
    5,
    Date.parse("2100-01-01"),
  );
  assert.match(expired.reason!, /过期/);
  const none = hotelPlanSelection(
    rows,
    { "2026-11-20": "k-3" },
    REAL_VIEW,
    undefined,
    NOW,
  );
  assert.match(none.reason!, /尚未载入/);
});

test("blocked reason only appears for a fully selected plan", () => {
  const rows = segmentHotelRows(hotels);
  const ok = hotelPlanSelection(
    rows,
    { "2026-11-20": "k-3" },
    REAL_VIEW,
    5,
    NOW,
  );
  const base = {
    ...ok,
    canSubmit: true,
    inactiveReason: "正在处理中，请稍候。",
  };
  assert.equal(planBlockedReason({ ...base, disabled: false }), null);
  assert.equal(
    planBlockedReason({ ...base, disabled: true }),
    "无法生成规划：正在处理中，请稍候。",
  );
  const partial = hotelPlanSelection(rows, {}, REAL_VIEW, 5, NOW);
  assert.equal(
    planBlockedReason({ ...partial, canSubmit: true, disabled: true }),
    null,
  );
});

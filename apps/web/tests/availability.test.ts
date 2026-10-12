/** UI prevents stale confirmation but does not replace the backend transaction. */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  planUnavailable,
  expiredHotels,
  bookingCanConfirm,
  partyLabel,
  planRefreshNotice,
  hotelQuoteNeedsRefresh,
} from "../src/lib/availability.ts";
import type { Plan, Hotels, Booking } from "../src/lib/api";

test("quote party includes original children and rooms independently of current conditions", () => {
  const original = { adults: 2, child_ages: [0, 8, 17], rooms: 2 };
  const edited = { adults: 1, child_ages: [5], rooms: 1 };
  assert.equal(partyLabel(original), "2成人 · 3名儿童（0、8、17岁） · 2间房");
  assert.equal(partyLabel(edited), "1成人 · 1名儿童（5岁） · 1间房");
  assert.deepEqual(original.child_ages, [0, 8, 17]);
  assert.equal(
    partyLabel({ adults: 2, child_ages: [], rooms: 1 }),
    "2成人 · 无儿童 · 1间房",
  );
});

test("missing or invalid child ages are unknown rather than no children", () => {
  for (const ages of [undefined, null, "8", [true], [18], [-1], [1.5]]) {
    assert.equal(
      partyLabel({ adults: 2, child_ages: ages, rooms: 1 }),
      "2成人 · 儿童信息未知 · 1间房",
    );
  }
  assert.equal(partyLabel({}), "成人数未知 · 儿童信息未知 · 间房数未知");
});

test("expiry boundary, changed conditions and stale evidence prevent confirmation", () => {
  const plan = {
    expired: false,
    conditions_changed: false,
    version_changed: false,
    needs_refresh: [],
    expires_at: "2026-11-01T00:00:00Z",
  } as unknown as Plan;
  const expires = Date.parse(plan.expires_at!);
  assert.equal(planUnavailable(plan, expires - 1), false);
  assert.equal(planUnavailable(plan, expires), true);
  for (const flag of [
    "expired",
    "conditions_changed",
    "version_changed",
  ] as const)
    assert.equal(planUnavailable({ ...plan, [flag]: true }, expires - 1), true);
  assert.equal(
    planUnavailable({ ...plan, needs_refresh: ["old"] }, expires - 1),
    true,
  );
  assert.equal(planUnavailable({ ...plan, expires_at: null }, expires), false);
});
test("an expired offer invalidates the displayed minimum even if comparison was previously valid", () => {
  const hotels = {
    cards: [
      { expires_at: "2026-11-01T00:00:00Z" },
      { expires_at: "2026-11-01T00:01:00Z" },
    ],
  } as unknown as Hotels;
  const expires = Date.parse(hotels.cards[0].expires_at);
  assert.equal(expiredHotels(hotels, expires - 1), false);
  assert.equal(expiredHotels(hotels, expires), true);
});

test("booking confirmation needs a current held quote and an unexpired hold", () => {
  const booking = {
    status: "held",
    offer: { request: { revision: 2 } },
    expires_at: "2026-11-01T00:00:00Z",
  } as unknown as Booking;
  const expires = Date.parse(booking.expires_at!);
  assert.equal(bookingCanConfirm(booking, 2, expires - 1), true);
  assert.equal(bookingCanConfirm(booking, 2, expires), false);
  assert.equal(bookingCanConfirm(booking, 3, expires - 1), false);
  for (const status of [
    "quoted",
    "confirmed",
    "unknown",
    "booked",
    "failed",
    "expired",
  ] as const)
    assert.equal(
      bookingCanConfirm({ ...booking, status }, 2, expires - 1),
      false,
    );
  assert.equal(
    bookingCanConfirm({ ...booking, expires_at: null }, 2, expires - 1),
    false,
  );
});

test("saved V1 keeps its identity when references require refresh and has no draft-expiry instruction", () => {
  const plan = {
    draft_id: null,
    version: 1,
    needs_refresh: ["place-old"],
    hotel: null,
    expired: false,
    conditions_changed: false,
    version_changed: false,
    expires_at: null,
  } as unknown as Plan;
  assert.equal(
    planRefreshNotice(plan, 0),
    "正式行程仍已保存；部分报价或参考信息需更新，使用前请重新查询。",
  );
  assert.equal(plan.version, 1);
  assert.deepEqual(plan.needs_refresh, ["place-old"]);
  assert.equal(planRefreshNotice({ ...plan, needs_refresh: [] }, 0), null);
  // Draft-only guards are not formal-version expiration, even in an old response.
  assert.equal(
    planRefreshNotice({ ...plan, needs_refresh: [], expired: true }, 0),
    null,
  );
});

test("draft restrictions remain distinct from the readability of saved versions", () => {
  const plan = {
    draft_id: "draft",
    needs_refresh: [],
    hotel: null,
    expired: false,
    conditions_changed: true,
    version_changed: false,
    expires_at: null,
  } as unknown as Plan;
  assert.equal(
    planRefreshNotice(plan, 0),
    "草稿已失效或引用需更新：请读取当前条件并重新生成草稿，不能确认此草稿。",
  );
  assert.equal(planUnavailable(plan, 0), true);
  assert.equal(
    planRefreshNotice({ ...plan, conditions_changed: false }, 0),
    null,
  );
});

test("hotel refresh is tied to its reference or quote expiry, not an unrelated place", () => {
  const plan = {
    draft_id: null,
    hotel_evidence_id: "hotel",
    hotel: { expires_at: "2026-11-01T00:00:00Z" },
    needs_refresh: ["place"],
  } as unknown as Plan;
  const expires = Date.parse(plan.hotel!.expires_at);
  assert.equal(hotelQuoteNeedsRefresh(plan, expires - 1), false);
  assert.equal(hotelQuoteNeedsRefresh(plan, expires), true);
  assert.equal(
    hotelQuoteNeedsRefresh({ ...plan, needs_refresh: ["hotel"] }, expires - 1),
    true,
  );
  assert.equal(
    hotelQuoteNeedsRefresh({ ...plan, hotel: null }, expires),
    false,
  );
  assert.equal(
    planRefreshNotice({ ...plan, needs_refresh: [] }, expires),
    "正式行程仍已保存；部分报价或参考信息需更新，使用前请重新查询。",
  );
});

test("each segmented hotel remains subject to quote expiry and missing references", () => {
  const expires = Date.parse("2026-11-01T00:00:00Z");
  const plan = {
    hotel: null,
    needs_refresh: [],
    hotel_stays: [
      { hotel_evidence_id: "a", hotel: { expires_at: "2026-11-01T00:00:00Z" } },
      { hotel_evidence_id: "b", hotel: { expires_at: "2026-11-02T00:00:00Z" } },
    ],
  } as unknown as Plan;
  assert.equal(hotelQuoteNeedsRefresh(plan, expires - 1), false);
  assert.equal(hotelQuoteNeedsRefresh(plan, expires), true);
  assert.equal(
    hotelQuoteNeedsRefresh({ ...plan, needs_refresh: ["b"] }, expires - 1),
    true,
  );
});

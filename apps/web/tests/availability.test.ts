/** UI prevents stale confirmation but does not replace the backend transaction. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { planUnavailable, expiredHotels } from "../src/lib/availability.ts";
import type { Plan, Hotels } from "../src/lib/api";

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

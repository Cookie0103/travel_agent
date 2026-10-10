/** The confirmed-trip list cannot infer absence from the active trip or an unavailable read. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { savedTripList } from "../src/lib/saved-trips.ts";
import type { TripSummary } from "../src/lib/api.ts";
const trip = (id: string, saved: boolean): TripSummary => ({
  session_id: id,
  city: id,
  created_at: "2026-10-08T00:00:00Z",
  start_date: null,
  end_date: null,
  last_activity_at: "2026-10-08T00:00:00Z",
  plan_id: saved ? `plan-${id}` : null,
  current_version: saved ? 1 : null,
});
const state = {
  identityPresent: true,
  restoring: false,
  busy: false,
  error: "",
  nextCursor: null,
};

test("all confirmed trips remain selectable when the active trip has no saved version", () => {
  const result = savedTripList(
    [trip("active", false), trip("Kyoto", true), trip("second", true)],
    state,
  );
  assert.equal(result.phase, "ready");
  assert.deepEqual(
    result.items.map((t) => t.session_id),
    ["Kyoto", "second"],
  );
});

test("failed, loading, missing identity and incomplete pages cannot claim no saved trips", () => {
  assert.equal(
    savedTripList([], { ...state, error: "请求失败503" }).phase,
    "error",
  );
  assert.equal(
    savedTripList([], { ...state, restoring: true }).phase,
    "loading",
  );
  assert.equal(
    savedTripList([], { ...state, identityPresent: false }).phase,
    "identity_missing",
  );
  assert.equal(
    savedTripList([trip("unconfirmed", false)], {
      ...state,
      nextCursor: "older",
    }).phase,
    "more",
  );
  assert.equal(
    savedTripList([trip("unconfirmed", false)], state).phase,
    "empty",
  );
});

test("retrying a failed list stays loading while its previous error has been cleared", () => {
  const retry = { ...state, busy: true, error: "" };
  assert.equal(savedTripList([], retry).phase, "loading");
});

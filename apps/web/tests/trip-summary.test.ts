import assert from "node:assert/strict";
import { test } from "node:test";
import { updateTripSummary } from "../src/lib/trip-summary.ts";
import type { TripSummary, RequestState } from "../src/lib/api";

test("current conversation facts update only this trip's label and preserve saved version metadata", () => {
  const current = {
    session_id: "current",
    city: null,
    start_date: null,
    end_date: null,
    current_version: 1,
    plan_id: "saved",
  } as unknown as TripSummary;
  const other = {
    session_id: "other",
    city: "京都",
    current_version: 2,
  } as unknown as TripSummary;
  const state = {
    city: "札幌",
    start_date: "2026-10-17",
    end_date: "2026-10-18",
  } as RequestState;
  const updated = updateTripSummary([current, other], "current", state);
  assert.deepEqual(updated[0], {
    ...current,
    city: "札幌",
    start_date: "2026-10-17",
    end_date: "2026-10-18",
  });
  assert.equal(updated[1], other);
  assert.equal(current.city, null);
});

test("clearing current facts clears stale labels without creating another trip", () => {
  const trip = {
    session_id: "current",
    city: "札幌",
    start_date: "2026-10-17",
    end_date: "2026-10-18",
  } as unknown as TripSummary;
  assert.deepEqual(updateTripSummary([trip], "current", {} as RequestState), [
    { ...trip, city: null, start_date: null, end_date: null },
  ]);
  assert.deepEqual(updateTripSummary([trip], "missing", {} as RequestState), [
    trip,
  ]);
});

import assert from "node:assert/strict";
import { test } from "node:test";
import { icsFilename } from "../src/lib/calendar-file.ts";

test("uses the versioned filename from the server", () => {
  assert.equal(
    icsFilename('attachment; filename="trip-v3.ics"'),
    "trip-v3.ics",
  );
});

test("falls back to trip.ics when the header is missing or unsafe", () => {
  assert.equal(icsFilename(null), "trip.ics");
  assert.equal(icsFilename("attachment"), "trip.ics");
  assert.equal(icsFilename('attachment; filename="../x.ics"'), "trip.ics");
  assert.equal(icsFilename('attachment; filename="trip.exe"'), "trip.ics");
});

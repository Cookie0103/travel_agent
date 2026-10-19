import assert from "node:assert/strict";
import { test } from "node:test";
import {
  hotelSelectionLive,
  lastHotelRunId,
  selectionProgress,
  type HotelSelectionView,
} from "../src/lib/hotel-flow.ts";

const view = (state: string, selected: Record<string, string> = {}) =>
  ({
    state,
    can_skip: state === "awaiting",
    segments: [
      ["京都", "2026-11-20", "2026-11-22"],
      ["大阪", "2026-11-22", "2026-11-24"],
    ].map(([city, check_in, check_out]) => ({
      city,
      check_in,
      check_out,
      selected: selected[check_in]
        ? {
            evidence_id: selected[check_in],
            hotel_name: `名-${selected[check_in]}`,
            source: "chat",
          }
        : null,
    })),
  }) as unknown as HotelSelectionView;
const rows = [
  {
    check_in: "2026-11-20",
    check_out: "2026-11-22",
    cards: [{ evidence_id: "a", hotel_name: "A" }],
  },
  {
    check_in: "2026-11-22",
    check_out: "2026-11-24",
    cards: [{ evidence_id: "b", hotel_name: "B" }],
  },
] as never;

test("the most recent turn with hotel cards is the one candidate", () => {
  const turns = [{ run_id: "1" }, { run_id: "2" }, { run_id: "3" }];
  const has = (r: { run_id: string }) => r.run_id !== "3";
  assert.equal(lastHotelRunId(turns, has), "2");
  assert.equal(
    lastHotelRunId([{ run_id: "1" }], () => false),
    undefined,
  );
});

test("earlier hotel turn stays live only while the server awaits and revision is current", () => {
  const base = {
    runId: "2",
    lastHotelRunId: "2",
    latestRunId: "3",
    revision: 4,
    cardRevision: 4,
  };
  assert.equal(hotelSelectionLive({ ...base, view: view("awaiting") }), true);
  assert.equal(hotelSelectionLive({ ...base, view: view("complete") }), false);
  assert.equal(hotelSelectionLive({ ...base, view: view("skipped") }), false);
  assert.equal(hotelSelectionLive({ ...base, view: undefined }), false);
  assert.equal(
    hotelSelectionLive({ ...base, view: view("awaiting"), revision: 5 }),
    false,
  );
  assert.equal(
    hotelSelectionLive({
      ...base,
      view: view("awaiting"),
      runId: "1",
      lastHotelRunId: "2",
    }),
    false,
    "only one set of live controls",
  );
});

test("latest turn keeps its previous behaviour", () => {
  assert.equal(
    hotelSelectionLive({
      runId: "3",
      lastHotelRunId: "3",
      latestRunId: "3",
      revision: 4,
      cardRevision: 4,
      view: undefined,
    }),
    true,
  );
});

test("progress comes from server picks, local clicks win, names always shown", () => {
  const p = selectionProgress(
    rows,
    { "2026-11-22": "b" },
    view("awaiting", { "2026-11-20": "zz" }),
  );
  assert.equal(p.count, 2);
  assert.equal(p.total, 2);
  assert.equal(p.names["2026-11-20"], "名-zz");
  assert.equal(selectionProgress(rows, {}, view("awaiting")).count, 0);
  assert.equal(selectionProgress(rows, {}, undefined).count, 0);
  assert.equal(
    selectionProgress(
      rows,
      { "2026-11-20": "a" },
      view("awaiting", { "2026-11-20": "zz" }),
    ).count,
    1,
  );
});

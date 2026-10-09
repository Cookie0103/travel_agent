import assert from "node:assert/strict";
import { test } from "node:test";
import { planDays, daySections, itineraryTime } from "../src/lib/itinerary.ts";

test("Tokyo dates and 17:00 boundary divide daytime/evening without losing indices", () => {
  const cards = [
    { start: "2026-10-10T15:30:00Z" },
    { start: "2026-10-11T16:59:00+09:00" },
    { start: "2026-10-11T17:00:00+09:00" },
    { start: "2026-10-12T09:00:00+09:00" },
  ];
  const days = planDays({ cards });
  assert.deepEqual(
    days.map((d) => d.day),
    ["2026-10-11", "2026-10-12"],
  );
  assert.deepEqual(
    daySections(days[0].items).map((s) => [
      s.label,
      s.items.map((x) => x.index),
    ]),
    [
      ["白天", [0, 1]],
      ["晚上", [2]],
    ],
  );
  assert.equal(days[1].items[0].index, 3);
  assert.equal(days[0].items[0].item, cards[0]);
});

test("malformed historic timestamps are explicitly undetermined, never guessed", () => {
  const days = planDays({
    cards: [
      { start: "" },
      { start: "bad" },
      { start: "2026-10-12T09:00:00+09:00" },
    ],
  });
  assert.equal(days[0].day, "时间待定");
  assert.equal(daySections(days[0].items)[0].label, "时间待定");
  assert.equal(itineraryTime(""), "时间待定");
  assert.equal(itineraryTime("bad"), "时间待定");
  assert.match(itineraryTime("2026-10-11T00:00:00Z"), /09:00/);
});

test("display segmentation preserves original order, repeated periods and empty days", () => {
  const cards = ["18:00", "09:00", "19:00"].map((time) => ({
    start: `2026-10-11T${time}:00+09:00`,
  }));
  const sections = daySections(planDays({ cards })[0].items);
  assert.deepEqual(
    sections.map((s) => s.label),
    ["晚上", "白天", "晚上"],
  );
  assert.deepEqual(
    sections.flatMap((s) => s.items.map((x) => x.index)),
    [0, 1, 2],
  );
  assert.deepEqual(planDays({ cards: [] }), []);
  assert.deepEqual(daySections([]), []);
});

test("date-only and zone-less historic values do not borrow browser timezone", () => {
  for (const value of [
    "2026-10-11",
    "2026-10-11T09:00:00",
    "2026-02-31T09:00:00+09:00",
  ]) {
    assert.equal(itineraryTime(value), "时间待定", value);
    assert.equal(planDays({ cards: [{ start: value }] })[0].day, "时间待定");
  }
});

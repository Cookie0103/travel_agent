import assert from "node:assert/strict";
import { test } from "node:test";
import { planDays, daySections, itineraryTime } from "../src/lib/itinerary.ts";
import * as itinerary from "../src/lib/itinerary.ts";
import type { Plan } from "../src/lib/api";

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

test("three cities and two stays group all thirty items with the correct nights", () => {
  const cities = ["大阪", "大阪", "神户", "神户", "京都"];
  const plan = {
    cards: Array.from({ length: 30 }, (_, index) => ({
      item_id: `item-${index}`,
      start: `2026-11-0${3 + Math.floor(index / 6)}T${String(8 + (index % 6)).padStart(2, "0")}:00:00+09:00`,
      city: cities[Math.floor(index / 6)],
    })),
    hotel: null,
    hotel_stays: [
      {
        check_in: "2026-11-03",
        check_out: "2026-11-05",
        hotel_evidence_id: "osaka",
        hotel: { hotel_name: "大阪合成酒店" },
      },
      {
        check_in: "2026-11-05",
        check_out: "2026-11-07",
        hotel_evidence_id: "kobe",
        hotel: { hotel_name: "神户合成酒店" },
      },
    ],
  } as unknown as Plan;
  const days = planDays(plan) as unknown as {
    cities: string[];
    stays: { hotel_evidence_id: string }[];
    transfer: boolean;
    items: { index: number }[];
  }[];
  assert.deepEqual(
    days.map((day) => day.cities),
    cities.map((city) => [city]),
  );
  assert.deepEqual(
    days.map((day) => day.stays.map((stay) => stay.hotel_evidence_id)),
    [["osaka"], ["osaka"], ["kobe"], ["kobe"], []],
  );
  assert.deepEqual(
    days.map((day) => day.transfer),
    [false, false, true, false, true],
  );
  assert.deepEqual(
    days.flatMap((day) => day.items.map((item) => item.index)),
    Array.from({ length: 30 }, (_, i) => i),
  );
});

test("only a fixed historic note suffix is removed, meaningful body wording stays", () => {
  const cleanNote = (
    itinerary as unknown as { cleanNote: (text: string) => string }
  ).cleanNote;
  assert.equal(typeof cleanNote, "function");
  assert.equal(cleanNote("城堡简介（模型概述，非来源核实）"), "城堡简介");
  assert.equal(cleanNote("花园简介（模型概述、非来源核实）"), "花园简介");
  assert.equal(cleanNote("这里有核实历史的展览。"), "这里有核实历史的展览。");
  assert.equal(
    cleanNote("（模型概述，非来源核实）是旧标记的解释。"),
    "（模型概述，非来源核实）是旧标记的解释。",
  );
});

test("historic single hotel nights follow quote dates and aliases do not create a transfer", () => {
  const plan = {
    cards: [
      { start: "2026-11-03T09:00:00+09:00", city: "京都" },
      { start: "2026-11-05T09:00:00+09:00", city: "Kyoto" },
    ],
    hotel_evidence_id: "legacy",
    hotel: { stay: { start_date: "2026-11-03", end_date: "2026-11-05" } },
    hotel_stays: [],
  } as unknown as Plan;
  const days = planDays(plan);
  assert.equal(days[0].stays.length, 1);
  assert.equal(days[1].stays.length, 0);
  assert.ok(days.every((day) => !day.transfer));
});

test("stay order cannot suppress a known later transfer when place cities are missing", () => {
  const plan = {
    cards: [
      { start: "2026-11-03T09:00:00+09:00" },
      { start: "2026-11-05T09:00:00+09:00" },
    ],
    hotel_stays: [
      { check_in: "2026-11-05", check_out: "2026-11-07" },
      { check_in: "2026-11-03", check_out: "2026-11-05" },
    ],
  } as unknown as Plan;
  assert.deepEqual(
    planDays(plan).map((day) => day.transfer),
    [false, true],
  );
});

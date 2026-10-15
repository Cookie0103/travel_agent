import assert from "node:assert/strict";
import { test } from "node:test";
import type { Hotels } from "../src/lib/api.ts";
import {
  segmentHotelRows,
  segmentHotelSelection,
} from "../src/lib/hotel-groups.ts";
import { moreTile } from "../src/lib/hotel-more.ts";

type Card = Hotels["cards"][number];
const cities = ["大阪", "京都", "奈良"];
const cards = cities.flatMap((city, index) =>
  Array.from(
    { length: 4 },
    (_, hotel) =>
      ({
        hotel_id: `hotel-${hotel}`,
        hotel_name: `${city}酒店${hotel + 1}`,
        offer_id: `offer-${index}-${hotel}`,
        evidence_id: `evidence-${index}-${hotel}`,
        stay: {
          city,
          start_date: `2026-11-0${index + 3}`,
          end_date: `2026-11-0${index + 4}`,
        } as Card["stay"],
        request_revision: 2,
        expires_at: "2026-11-01T00:00:00Z",
      }) as Card,
  ),
);
const hotels: Hotels = {
  component: "hotel_comparison",
  comparison: {
    comparable: false,
    lowest_offer_ids: [],
    reasons: [],
    scope: "不同住宿段",
    room_preferences_question: null,
    budget_relation: null,
  },
  total_found: null,
  more_url: null,
  more_url_scope: null,
  cards,
  segments: cities.map((city, index) => ({
    city,
    check_in: `2026-11-0${index + 3}`,
    check_out: `2026-11-0${index + 4}`,
    evidence_ids: cards
      .slice(index * 4, index * 4 + 4)
      .map((card) => card.evidence_id),
    more_url: `https://travel.rakuten.co.jp/${index}.html`,
    more_url_scope: "destination",
    total_found: 100 + index,
    comparison: {
      comparable: true,
      lowest_offer_ids: [],
      reasons: [],
      scope: city,
      room_preferences_question: null,
      budget_relation: null,
    },
  })),
};
const now = Date.parse("2026-10-11T00:00:00Z");

test("three overnight segments have their own three candidates and Rakuten links", () => {
  const rows = segmentHotelRows(hotels);
  assert.deepEqual(
    rows.map((row) => row.city),
    cities,
  );
  assert.deepEqual(
    rows.map((row) => row.cards.length),
    [3, 3, 3],
  );
  assert.deepEqual(
    rows.map((row) => moreTile(row)?.href),
    hotels.segments?.map((row) => row.more_url),
  );
  assert.equal(segmentHotelRows({ ...hotels, segments: undefined }).length, 0);
});

test("a selection cannot start planning until every segment has a current hotel", () => {
  const rows = segmentHotelRows(hotels);
  const choices = Object.fromEntries(
    rows.slice(0, 2).map((row) => [row.check_in, row.cards[0].evidence_id]),
  );
  assert.equal(segmentHotelSelection(rows, choices, 2, now), undefined);
  choices[rows[2].check_in] = rows[2].cards[0].evidence_id;
  const selected = segmentHotelSelection(rows, choices, 2, now);
  assert.ok(selected);
  assert.equal(selected.expected_revision, 2);
  assert.deepEqual(
    selected.hotel_stays.map((stay) => stay.hotel_evidence_id),
    rows.map((row) => row.cards[0].evidence_id),
  );
  assert.deepEqual(
    selected.hotel_stays.map((stay) => [stay.check_in, stay.check_out]),
    rows.map((row) => [row.check_in, row.check_out]),
  );
  assert.match(selected.text, /大阪酒店1/);
  assert.match(selected.text, /京都酒店1/);
  assert.match(selected.text, /奈良酒店1/);
  assert.equal(segmentHotelSelection(rows, choices, 3, now), undefined);
  assert.equal(
    segmentHotelSelection(rows, choices, 2, Date.parse("2026-11-02")),
    undefined,
  );
});

test("a hotel from another segment cannot satisfy an unselected row", () => {
  const rows = segmentHotelRows(hotels);
  const choices = Object.fromEntries(
    rows.map((row) => [row.check_in, rows[0].cards[0].evidence_id]),
  );
  assert.equal(segmentHotelSelection(rows, choices, 2, now), undefined);
  assert.equal(
    segmentHotelSelection([{ ...rows[0], cards: [] }], choices, 2, now),
    undefined,
  );
});

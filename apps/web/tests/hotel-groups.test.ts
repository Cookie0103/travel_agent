import assert from "node:assert/strict";
import { test } from "node:test";
import { hotelGroups, selectedHotelOffer } from "../src/lib/hotel-groups.ts";
import type { Hotels } from "../src/lib/api.ts";
type Card = Hotels["cards"][number];
const card = (hotel: string, offer: string, total: string): Card =>
  ({
    hotel_id: hotel,
    hotel_name: "同名ホテル",
    offer_id: offer,
    total,
    room_type: "ツイン",
    evidence_id: `e-${offer}`,
  }) as Card;
test("two packages make one hotel card; same names never merge different ids", () => {
  const rows = [
    card("A", "a1", "30000"),
    card("A", "a2", "20000"),
    card("B", "b1", "10000"),
    card("C", "c1", "40000"),
    card("D", "d1", "50000"),
  ];
  const groups = hotelGroups(rows);
  assert.equal(groups.length, 4);
  assert.deepEqual(
    groups.map((g) => g.hotel_id),
    ["A", "B", "C", "D"],
  );
  assert.deepEqual(
    groups[0].offers.map((o) => o.offer_id),
    ["a1", "a2"],
  );
  assert.equal(rows.length, 5);
});
test("selection binds the full offer; stale id falls back to first without writes", () => {
  const first = card("A", "a1", "30000"),
    second = card("A", "a2", "20000");
  assert.equal(selectedHotelOffer([first, second], "a2"), second);
  assert.equal(selectedHotelOffer([first, second], "old"), first);
  assert.equal(selectedHotelOffer([], "old"), undefined);
  assert.equal(selectedHotelOffer([first, second], "a2")?.evidence_id, "e-a2");
});

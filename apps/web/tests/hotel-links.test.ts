import assert from "node:assert/strict";
import { test } from "node:test";
import { hotelLinks } from "../src/lib/hotel-links.ts";

test("hotel introduction never uses reservation or plan fallback", () => {
  const links = hotelLinks({
    hotel_info_url: "https://example.com/info",
    plan_list_url: "https://example.com/plans",
    reservation_url: "https://example.com/reserve",
    booking_url: "https://example.com/legacy",
  });
  assert.deepEqual(links, {
    info: "https://example.com/info",
    plans: "https://example.com/plans",
    reservation: "https://example.com/reserve",
    legacy: undefined,
  });
});
test("old cards keep separately named quote link, unknown info and unsafe links stay disabled", () => {
  assert.deepEqual(hotelLinks({ booking_url: "https://example.com/old" }), {
    info: undefined,
    plans: undefined,
    reservation: undefined,
    legacy: "https://example.com/old",
  });
  assert.deepEqual(
    hotelLinks({
      hotel_info_url: "javascript:alert(1)",
      plan_list_url: "http://example.com/plain",
      reservation_url: "data:text/html,bad",
      booking_url: "https://example.com/old",
    }),
    {
      info: undefined,
      plans: undefined,
      reservation: undefined,
      legacy: undefined,
    },
  );
  assert.equal(
    hotelLinks({ hotel_info_url: null, booking_url: "https://example.com/old" })
      .info,
    undefined,
  );
});

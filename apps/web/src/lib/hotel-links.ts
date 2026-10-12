import { sourceHref } from "./api.ts";
import type { Hotels } from "./api.ts";

type Card = Hotels["cards"][number];
type Links = Pick<Card, "booking_url"> &
  Partial<Pick<Card, "hotel_info_url" | "plan_list_url" | "reservation_url">>;

/** Legacy fallback cannot prove which page it links to. */
export function hotelLinks(card: Links) {
  const safe = (value: string | null | undefined) =>
    value ? sourceHref(value) : undefined;
  const old =
    card.hotel_info_url === undefined &&
    card.plan_list_url === undefined &&
    card.reservation_url === undefined;
  return {
    info: safe(card.hotel_info_url),
    plans: safe(card.plan_list_url),
    reservation: safe(card.reservation_url),
    legacy: old ? safe(card.booking_url) : undefined,
  };
}

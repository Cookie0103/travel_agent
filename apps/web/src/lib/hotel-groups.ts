/** Group canonical offers by provider hotel ID; never merge prices or IDs. */
import type { Hotels } from "./api";
type Card = Hotels["cards"][number];
export function hotelGroups(cards: Card[]) {
  const groups = new Map<string, { hotel_id: string; offers: Card[] }>();
  for (const card of cards) {
    let group = groups.get(card.hotel_id);
    if (!group) {
      group = { hotel_id: card.hotel_id, offers: [] };
      groups.set(card.hotel_id, group);
    }
    group.offers.push(card);
  }
  return [...groups.values()];
}
export function selectedHotelOffer(
  offers: Card[],
  selected: string | undefined,
): Card | undefined {
  return offers.find((card) => card.offer_id === selected) ?? offers[0];
}

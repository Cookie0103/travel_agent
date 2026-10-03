/** UI expiry guards mirror server timestamps; confirmation still rechecks in the transaction. */
import type { Plan, Hotels } from "./api";
export function planUnavailable(plan: Plan, now: number): boolean {
  return (
    plan.expired ||
    plan.conditions_changed ||
    plan.version_changed ||
    plan.needs_refresh.length > 0 ||
    !!(plan.expires_at && now >= Date.parse(plan.expires_at))
  );
}
export function expiredHotels(hotels: Hotels, now: number): boolean {
  return hotels.cards.some((card) => now >= Date.parse(card.expires_at));
}

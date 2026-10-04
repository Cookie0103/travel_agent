/** UI expiry guards mirror server timestamps; confirmation still rechecks in the transaction. */
import type { Plan, Hotels, Booking } from "./api";

export function partyLabel(stay: Record<string, unknown>): string {
  const count = (value: unknown, label: string) =>
    typeof value === "number" && Number.isInteger(value) && value > 0
      ? `${value}${label}`
      : `${label}数未知`;
  const ages = stay.child_ages;
  const children =
    Array.isArray(ages) &&
    ages.every((age) => Number.isInteger(age) && age >= 0 && age <= 17)
      ? ages.length
        ? `${ages.length}名儿童（${ages.join("、")}岁）`
        : "无儿童"
      : "儿童信息未知";
  return `${count(stay.adults, "成人")} · ${children} · ${count(stay.rooms, "间房")}`;
}

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

export function bookingCanConfirm(
  booking: Booking,
  revision: number | undefined,
  now: number,
): boolean {
  return (
    booking.status === "held" &&
    booking.offer.request.revision === revision &&
    !!booking.expires_at &&
    now < Date.parse(booking.expires_at)
  );
}

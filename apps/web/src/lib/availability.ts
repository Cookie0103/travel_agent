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
/** A saved version remains readable; only its references/quotes need a fresh query. */
export function hotelQuoteNeedsRefresh(plan: Plan, now: number): boolean {
  return !!(
    plan.hotel &&
    ((plan.hotel_evidence_id &&
      plan.needs_refresh.includes(plan.hotel_evidence_id)) ||
      now >= Date.parse(plan.hotel.expires_at))
  );
}

export function planRefreshNotice(plan: Plan, now: number): string | null {
  if (plan.draft_id)
    return planUnavailable(plan, now)
      ? "草稿已失效或引用需更新：请读取当前条件并重新生成草稿，不能确认此草稿。"
      : null;
  return plan.needs_refresh.length > 0 || hotelQuoteNeedsRefresh(plan, now)
    ? "正式行程仍已保存；部分报价或参考信息需更新，使用前请重新查询。"
    : null;
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

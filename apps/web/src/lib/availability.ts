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

/** Backend amounts are decimal strings in the offer's own currency; never assume yen. Null stays "未知", never 0. */
export function moneyLabel(
  amount: string | null | undefined,
  currency: string,
): string {
  if (
    amount == null ||
    amount.trim() === "" ||
    !Number.isFinite(Number(amount))
  )
    return "未知";
  try {
    // "30,000 JPY": grouped number plus ISO code, using the currency's own decimal places.
    const digits = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
    }).resolvedOptions().minimumFractionDigits;
    const number = new Intl.NumberFormat("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(Number(amount));
    return `${number} ${currency}`;
  } catch {
    return `${amount} ${currency}`;
  }
}

/** "3,000–9,000 JPY"; a missing bound is shown as the given placeholder. */
export function moneyRangeLabel(
  lower: string | null | undefined,
  upper: string | null | undefined,
  currency: string,
  missing: { lower: string; upper: string },
): string {
  const part = (value: string | null | undefined, fallback: string) =>
    moneyLabel(value, currency).replace(` ${currency}`, "") === "未知"
      ? fallback
      : moneyLabel(value, currency).replace(` ${currency}`, "");
  return `${part(lower, missing.lower)}–${part(upper, missing.upper)} ${currency}`;
}

/** "+1,200 JPY" for a positive excess only; zero, negative or unparseable amounts render nothing. */
export function budgetExcessLabel(
  amount: string | null | undefined,
  currency: string,
): string | null {
  if (amount == null || amount.trim() === "" || !(Number(amount) > 0))
    return null;
  return `+${moneyLabel(amount, currency)}`;
}

/** Reason hotel actions are unavailable because of where the card sits, not because of the offer itself. */
export function inactiveHotelReason(state: {
  latest: boolean;
  busy: boolean;
}): string | null {
  if (!state.latest) return "这是历史对话中的结果，请在最新一轮结果里操作。";
  if (state.busy) return "正在处理中，请稍候。";
  return null;
}

/** Visible reason a hotel offer cannot be held/selected right now; null when it can. */
export function hotelHoldBlockReason(state: {
  expired: boolean;
  totalKnown: boolean;
  /** null: the current conditions revision is not loaded yet. */
  revisionMatches: boolean | null;
}): string | null {
  if (state.expired) return "报价已过期，请重新比较酒店获取新报价。";
  if (state.revisionMatches === null)
    return "当前条件版本尚未载入，请稍候或刷新后再操作。";
  if (!state.revisionMatches)
    return "此报价基于旧条件，请重新比较酒店后再操作。";
  if (!state.totalKnown) return "总价未知，无法暂留。";
  return null;
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
    (plan.hotel &&
      ((plan.hotel_evidence_id &&
        plan.needs_refresh.includes(plan.hotel_evidence_id)) ||
        now >= Date.parse(plan.hotel.expires_at))) ||
    plan.hotel_stays?.some(
      (stay) =>
        !stay.hotel ||
        plan.needs_refresh.includes(stay.hotel_evidence_id) ||
        now >= Date.parse(stay.hotel.expires_at),
    )
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

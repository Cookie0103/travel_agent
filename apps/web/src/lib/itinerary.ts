/** Display-only Tokyo calendar/period grouping; never sorts or changes plan evidence. */
const dayFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Tokyo",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const hourFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Tokyo",
  hour: "2-digit",
  hourCycle: "h23",
});
const timeFormat = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Tokyo",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const parsed = (value: string) => {
  const match =
    /^(\d{4}-\d{2}-\d{2})T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.exec(
      value,
    );
  if (!match) return undefined;
  const calendar = new Date(`${match[1]}T00:00:00Z`);
  if (
    Number.isNaN(calendar.getTime()) ||
    !calendar.toISOString().startsWith(match[1])
  )
    return undefined;
  const time = new Date(value);
  return Number.isNaN(time.getTime()) ? undefined : time;
};
export const itineraryDay = (value: string) => {
  const time = parsed(value);
  return time ? dayFormat.format(time) : undefined;
};
export const itineraryTime = (value: string) => {
  const time = parsed(value);
  return time ? timeFormat.format(time) : "时间待定";
};
export function planDays<T extends { start: string }>(plan: { cards: T[] }) {
  const days: { day: string; items: { item: T; index: number }[] }[] = [];
  plan.cards.forEach((item, index) => {
    const day = itineraryDay(item.start) ?? "时间待定";
    const last = days.at(-1);
    if (last?.day === day) last.items.push({ item, index });
    else days.push({ day, items: [{ item, index }] });
  });
  return days;
}
export function daySections<T extends { start: string }>(
  items: { item: T; index: number }[],
) {
  const sections: { label: string; items: typeof items }[] = [];
  for (const entry of items) {
    const time = parsed(entry.item.start);
    const label = !time
      ? "时间待定"
      : Number(hourFormat.format(time)) < 17
        ? "白天"
        : "晚上";
    const last = sections.at(-1);
    if (last?.label === label) last.items.push(entry);
    else sections.push({ label, items: [entry] });
  }
  return sections;
}

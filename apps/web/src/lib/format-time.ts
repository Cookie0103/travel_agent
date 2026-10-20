/** One display format for timestamps: fixed Asia/Tokyo, independent of the browser zone. */
const format = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Tokyo",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

export function formatTokyo(value: string): string {
  const time = new Date(value);
  return Number.isNaN(time.getTime()) ? value : format.format(time);
}

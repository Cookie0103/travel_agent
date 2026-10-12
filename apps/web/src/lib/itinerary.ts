/** Display-only Tokyo calendar/period grouping; never sorts or changes plan evidence. */
import type { Plan } from "./api";

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
const cityKey = (city: string) => {
  const key = city.replace(/\s/g, "").toLowerCase().replace(/市$/, "");
  const aliases: Record<string, string> = {
    kyoto: "京都",
    osaka: "大阪",
    kobe: "神戸",
    神户: "神戸",
    tokyo: "東京",
    东京: "東京",
    nara: "奈良",
    sapporo: "札幌",
    hakone: "箱根",
    okinawa: "沖縄",
    冲绳: "沖縄",
    naha: "那覇",
    那霸: "那覇",
  };
  return aliases[key] ?? key;
};

export function cleanNote(note: string): string {
  return note.replace(
    /\s*[（(]模型(?:概述|撰写)[，,、]\s*非来源核实[）)]\s*$/u,
    "",
  );
}

export function planDays<
  T extends { start: string; city?: string | null },
>(plan: {
  cards: T[];
  hotel?: Plan["hotel"];
  hotel_evidence_id?: string | null;
  hotel_stays?: Plan["hotel_stays"];
}) {
  const days: {
    day: string;
    items: { item: T; index: number }[];
    cities: string[];
    stays: Plan["hotel_stays"];
    transfer: boolean;
  }[] = [];
  plan.cards.forEach((item, index) => {
    const day = itineraryDay(item.start) ?? "时间待定";
    const last = days.at(-1);
    if (last?.day === day) last.items.push({ item, index });
    else
      days.push({
        day,
        items: [{ item, index }],
        cities: [],
        stays: [],
        transfer: false,
      });
  });
  let stays = plan.hotel_stays ?? [];
  if (!stays.length && plan.hotel) {
    const { start_date, end_date } = plan.hotel.stay;
    if (typeof start_date === "string" && typeof end_date === "string")
      stays = [
        {
          check_in: start_date,
          check_out: end_date,
          hotel_evidence_id: plan.hotel_evidence_id ?? plan.hotel.evidence_id,
          hotel: plan.hotel,
        },
      ];
  }
  const firstCheckIn = stays.reduce(
    (first, stay) => (stay.check_in < first ? stay.check_in : first),
    stays[0]?.check_in ?? "",
  );
  days.forEach((day, index) => {
    for (const { item } of day.items) {
      if (
        item.city &&
        !day.cities.some((city) => cityKey(city) === cityKey(item.city!))
      )
        day.cities.push(item.city);
    }
    day.stays = stays.filter(
      (stay) => stay.check_in <= day.day && day.day < stay.check_out,
    );
    const previousCities = days[index - 1]?.cities ?? [];
    day.transfer =
      !!plan.hotel_stays?.length &&
      (day.cities.length > 1 ||
        (previousCities.length > 0 &&
          day.cities.some(
            (city) =>
              !previousCities.some(
                (previous) => cityKey(previous) === cityKey(city),
              ),
          )) ||
        stays.some(
          (stay) => stay.check_in === day.day && stay.check_in > firstCheckIn,
        ));
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

/** Group current bounded feedback; never infer a validator state from a message. */
import { itineraryDay } from "./itinerary.ts";
import type { components } from "./api-types";
type Check = components["schemas"]["UiValidationCheck"];
const labels: Record<string, string> = {
  opening_hours: "营业时间",
  route_missing: "路线信息",
  route_source: "路线来源",
  route_duration: "路线耗时",
  route_gap: "路线时间",
  route_departure: "路线出发时间",
  route_scope: "路线范围",
  route_unexpected: "路线安排",
  route_fare: "路线费用",
  trip_dates: "旅行日期",
  visit_duration: "停留时长",
  overlap: "时间重叠",
  departure_time: "出发时间",
  place_source: "地点来源",
  city: "目的地",
  pace_warning: "景点密度",
  repeated_place_warning: "重复景点",
  hotel_missing: "住宿选择",
  hotel_source: "住宿来源",
  hotel_total: "住宿总价",
  currency: "报价币种",
  budget_missing: "全程预算",
  budget: "全程预算",
  other_costs: "其他费用",
  free_text_constraints: "自由文本条件",
  lodging_budget_conflict: "预算层级",
  lodging_budget_warning: "预算层级",
  lodging_budget_unknown: "预算层级",
};
export function validationGroups(checks: Check[]) {
  const groups: { label: string; status: Check["status"]; checks: Check[] }[] =
    [];
  const byKey = new Map<string, (typeof groups)[number]>();
  for (const check of checks) {
    if (check.status === "verified") continue;
    const key = `${check.status}:${check.code}`;
    let group = byKey.get(key);
    if (!group) {
      group = {
        label: Object.hasOwn(labels, check.code)
          ? labels[check.code]
          : "其他校验",
        status: check.status,
        checks: [],
      };
      groups.push(group);
      byKey.set(key, group);
    }
    group.checks.push(check);
  }
  return groups.sort(
    (a, b) => Number(b.status === "conflict") - Number(a.status === "conflict"),
  );
}
export function checkTargets(
  subject: string,
  cards: { start: string }[],
): number[] {
  const item = /^item:(0|[1-9]\d*)$/.exec(subject);
  if (item) {
    const index = Number(item[1]);
    return index < cards.length ? [index] : [];
  }
  const route = /^route:(0|[1-9]\d*)->(0|[1-9]\d*)$/.exec(subject);
  if (route) {
    const from = Number(route[1]),
      to = Number(route[2]);
    return to === from + 1 && to < cards.length ? [from, to] : [];
  }
  const day = /^day:(\d{4}-\d{2}-\d{2})$/.exec(subject);
  if (day)
    return cards.flatMap((card, index) =>
      itineraryDay(card.start) === day[1] ? [index] : [],
    );
  return [];
}

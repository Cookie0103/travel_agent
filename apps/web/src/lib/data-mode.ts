/** Source labels distinguish synthetic evaluation cards from provider data. */
import type { components } from "./api-types";

type Mode = components["schemas"]["PlanCard"]["data_mode"];

export function sourceLabel(mode: Mode): string {
  switch (mode) {
    case "synthetic":
      return "测试数据，不是真实酒店/地点";
    case "live":
      return "乐天实时";
    case "snapshot":
      return "历史快照";
    default:
      return "模拟报价";
  }
}

/** Only fixture rooms support the simulated hold; provider quotes are selected. */
export function canHoldHotel(mode: Mode, selectingSegment = false): boolean {
  return mode === "fixture" && !selectingSegment;
}

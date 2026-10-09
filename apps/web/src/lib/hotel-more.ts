/** Pure helpers for the hotel strip: "see more on Rakuten" tile and scroll-button state. */
import type { Hotels } from "./api.ts";

type More = Partial<
  Pick<Hotels, "more_url" | "more_url_scope" | "total_found">
>;

const RAKUTEN_TRAVEL_HOST = "travel.rakuten.co.jp";

/** Only plain https links on Rakuten Travel hosts; no credentials, no custom port. */
export function safeRakutenTravelUrl(
  value: string | null | undefined,
): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    const hostOk =
      host === RAKUTEN_TRAVEL_HOST || host.endsWith(`.${RAKUTEN_TRAVEL_HOST}`);
    if (url.protocol !== "https:" || !hostOk) return undefined;
    if (url.username || url.password || url.port) return undefined;
    return url.href;
  } catch {
    return undefined;
  }
}

/** Tile content, or undefined when there is no safe link (never render a dead tile). */
export function moreTile(hotels: More) {
  const href = safeRakutenTravelUrl(hotels.more_url);
  if (!href) return undefined;
  const total = hotels.total_found;
  const title =
    "在乐天查看更多酒店" +
    (typeof total === "number" && Number.isFinite(total) && total > 0
      ? `（本次搜索范围内有空房 ${total} 家）`
      : "");
  const note =
    hotels.more_url_scope === "search"
      ? "将打开乐天的搜索结果页。"
      : "将打开乐天的目的地酒店页，入住日期和人数需要在乐天重新选择。";
  return { href, title, note };
}

/** Prev/next availability from scroll geometry (1px tolerance for fractional scroll). */
export function scrollButtons(
  scrollLeft: number,
  clientWidth: number,
  scrollWidth: number,
) {
  const overflow = scrollWidth - clientWidth > 1;
  return {
    overflow,
    canPrev: overflow && scrollLeft > 1,
    canNext: overflow && scrollLeft + clientWidth < scrollWidth - 1,
  };
}

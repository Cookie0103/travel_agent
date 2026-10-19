/** Pure rules for the choose-hotel-then-plan flow: server selection state, skip, empty results. */
import type { components } from "./api-types";
import type { Hotels } from "./api";
import { segmentHotelRows } from "./hotel-groups.ts";

export type HotelSelectionView = components["schemas"]["HotelSelectionView"];
type Rows = ReturnType<typeof segmentHotelRows>;

export const SKIP_HOTELS_TEXT = "先不选酒店，先排行程";

/** Skip is its own structured message; it never carries hotel stays or a card selection. */
export function skipHotelsMessage(revision: number) {
  return {
    expected_revision: revision,
    skip_hotels: true as const,
    text: SKIP_HOTELS_TEXT,
  };
}

/**
 * Picks per segment start date: a local click wins, otherwise a pick the server already
 * recorded (chat or assignment card) that still belongs to a displayed candidate.
 */
export function effectiveChoices(
  rows: Rows,
  local: Record<string, string>,
  view: HotelSelectionView | undefined,
): Record<string, string> {
  const result: Record<string, string> = {};
  for (const row of rows) {
    const mine = local[row.check_in];
    const recorded = view?.segments.find(
      (segment) =>
        segment.check_in === row.check_in &&
        segment.check_out === row.check_out,
    )?.selected?.evidence_id;
    const chosen =
      mine ??
      (recorded && row.cards.some((c) => c.evidence_id === recorded)
        ? recorded
        : undefined);
    if (chosen) result[row.check_in] = chosen;
  }
  return result;
}

/** Honest empty-result notice; the link is only the Rakuten entry page the server supplied. */
export function emptyHotelNotice(hotels: Hotels) {
  if (hotels.cards.length) return null;
  const url = hotels.comparison.search_url;
  let href: string | undefined;
  try {
    href = url && new URL(url).protocol === "https:" ? url : undefined;
  } catch {
    href = undefined;
  }
  return {
    message: "这次没有找到可展示的酒店报价。",
    hint: "你可以打开乐天旅游自己找，把乐天酒店链接或酒店名直接贴给我；也可以先不选酒店，先排行程。",
    href,
  };
}

/** Most recent turn that carries a hotel presentation (not merely the latest turn). */
export function lastHotelRunId<T extends { run_id: string }>(
  turns: T[],
  hasHotels: (turn: T) => boolean,
): string | undefined {
  for (let i = turns.length - 1; i >= 0; i--)
    if (hasHotels(turns[i])) return turns[i].run_id;
  return undefined;
}

/**
 * Whether this turn's hotel controls are actionable. The latest turn always was; an earlier
 * turn is live only if it is the last hotel turn, the server still awaits a selection and
 * the card revision is current. Everything else is history.
 */
export function hotelSelectionLive(s: {
  runId: string;
  lastHotelRunId: string | undefined;
  latestRunId: string | undefined;
  revision: number | undefined;
  cardRevision: number | undefined;
  view: HotelSelectionView | undefined;
}): boolean {
  if (s.runId === s.latestRunId) return true;
  return (
    s.runId === s.lastHotelRunId &&
    s.view?.state === "awaiting" &&
    s.revision !== undefined &&
    s.revision === s.cardRevision
  );
}

/** "已选 N/M 段" and per-segment names from the server, merged with unsent local clicks. */
export function selectionProgress(
  rows: Rows,
  local: Record<string, string>,
  view: HotelSelectionView | undefined,
) {
  const names: Record<string, string> = {};
  let count = 0;
  for (const row of rows) {
    const mine = local[row.check_in]
      ? row.cards.find((c) => c.evidence_id === local[row.check_in])
      : undefined;
    const server = view?.segments.find(
      (s) => s.check_in === row.check_in && s.check_out === row.check_out,
    )?.selected;
    const name = mine?.hotel_name ?? server?.hotel_name;
    if (name) {
      names[row.check_in] = name;
      count += 1;
    }
  }
  return { count, total: rows.length, names };
}

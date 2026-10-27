/** Pure rules for the choose-hotel-then-plan flow: server selection state, skip, empty results. */
import type { components } from "./api-types";
import type { Hotels } from "./api";
import { segmentHotelRows, type HotelSelection } from "./hotel-groups.ts";

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

export const RECLICK_REASON = "请再点一次该酒店的“选用此酒店”";
export const STALE_REASON = "所选酒店报价基于旧条件，请重新比较酒店后再选";
export const EXPIRED_REASON = "所选酒店报价已过期，请重新比较酒店后再选";
export const NO_REVISION_REASON = "当前条件版本尚未载入，请稍候或刷新页面";

/**
 * Submit payload for the plan button over the merged selection. Enablement and payload use
 * evidence ids and segment dates only, never hotel names. A local click wins (its card must be
 * current); otherwise the server-recorded pick is used by evidence id with the segment's own
 * dates, so chat/assignment picks count without a local click. `reason` is set only when every
 * segment has a pick but the pick cannot form a valid stay; a segment without any pick yields {}.
 */
export function hotelPlanSelection(
  rows: Rows,
  local: Record<string, string>,
  view: HotelSelectionView | undefined,
  revision: number | undefined,
  now: number,
): { selection?: HotelSelection & { text: string }; reason?: string } {
  if (!rows.length) return {};
  const picked: { evidence_id: string; hotel_name: string }[] = [];
  let reason: string | undefined;
  for (const row of rows) {
    const mine = local[row.check_in]
      ? row.cards.find((c) => c.evidence_id === local[row.check_in])
      : undefined;
    if (mine) {
      const expires = Date.parse(mine.expires_at);
      if (revision === undefined) reason ??= NO_REVISION_REASON;
      else if (mine.request_revision !== revision) reason ??= STALE_REASON;
      else if (!Number.isFinite(expires) || expires <= now)
        reason ??= EXPIRED_REASON;
      picked.push(mine);
      continue;
    }
    const server = view?.segments.find(
      (s) => s.check_in === row.check_in && s.check_out === row.check_out,
    )?.selected;
    if (!server) return {};
    if (!server.evidence_id) {
      reason ??= RECLICK_REASON;
      continue;
    }
    picked.push({
      evidence_id: server.evidence_id,
      hotel_name: server.hotel_name ?? "",
    });
  }
  if (reason || revision === undefined) return reason ? { reason } : {};
  return {
    selection: {
      expected_revision: revision,
      hotel_stays: rows.map((row, i) => ({
        check_in: row.check_in,
        check_out: row.check_out,
        hotel_evidence_id: picked[i].evidence_id,
      })),
      text:
        "我已选齐各住宿段酒店，请保留已确认条件，按这些酒店统一规划每天行程：\n" +
        rows
          .map(
            (row, i) =>
              `${row.city} ${row.check_in}→${row.check_out}：${picked[i].hotel_name}`,
          )
          .join("\n") +
        "\n每晚回到当晚所选酒店；先安排时间与交通缓冲，再按相邻项目结束时间查询路线，校验通过后展示草稿供我确认保存。",
    },
  };
}

/** Why a fully selected plan button is not actionable, or null when it is (or not fully selected). */
export function planBlockedReason(s: {
  selection?: unknown;
  reason?: string | undefined;
  disabled: boolean;
  inactiveReason?: string | null;
  canSubmit: boolean;
}): string | null {
  if (s.reason) return `无法生成规划：${s.reason}`;
  if (!s.selection) return null;
  if (s.disabled)
    return `无法生成规划：${s.inactiveReason ?? "页面正在处理上一条消息，请稍候"}`;
  if (!s.canSubmit) return "无法生成规划：当前页面不能提交，请刷新";
  return null;
}

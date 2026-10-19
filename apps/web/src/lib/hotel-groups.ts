/** Group canonical offers by provider hotel ID; never merge prices or IDs. */
import type { Hotels } from "./api";
type Card = Hotels["cards"][number];
export function hotelGroups(cards: Card[]) {
  const groups = new Map<string, { hotel_id: string; offers: Card[] }>();
  for (const card of cards) {
    let group = groups.get(card.hotel_id);
    if (!group) {
      group = { hotel_id: card.hotel_id, offers: [] };
      groups.set(card.hotel_id, group);
    }
    group.offers.push(card);
  }
  return [...groups.values()];
}
export function selectedHotelOffer(
  offers: Card[],
  selected: string | undefined,
): Card | undefined {
  return offers.find((card) => card.offer_id === selected) ?? offers[0];
}

type Segment = NonNullable<Hotels["segments"]>[number];
type SegmentHotelRow = Segment & { cards: Card[] };
export type HotelSelection = {
  expected_revision: number;
  hotel_stays: {
    check_in: string;
    check_out: string;
    hotel_evidence_id: string;
  }[];
};
export function segmentHotelRows(hotels: Hotels): SegmentHotelRow[] {
  return (hotels.segments ?? []).map((segment) => ({
    ...segment,
    cards: hotelGroups(
      hotels.cards.filter((card) =>
        segment.evidence_ids.includes(card.evidence_id),
      ),
    ).flatMap((group) => group.offers),
  }));
}
export function segmentHotelSelection(
  rows: SegmentHotelRow[],
  choices: Record<string, string>,
  revision: number | undefined,
  now: number,
): (HotelSelection & { text: string }) | undefined {
  if (!rows.length || revision === undefined) return undefined;
  const picked = rows.map((row) =>
    row.cards.find((card) => card.evidence_id === choices[row.check_in]),
  );
  if (
    picked.some(
      (card) =>
        !card ||
        card.request_revision !== revision ||
        !Number.isFinite(Date.parse(card.expires_at)) ||
        Date.parse(card.expires_at) <= now,
    )
  )
    return undefined;
  const hotel_stays = rows.map((row, index) => ({
    check_in: row.check_in,
    check_out: row.check_out,
    hotel_evidence_id: picked[index]!.evidence_id,
  }));
  return {
    expected_revision: revision,
    hotel_stays,
    text:
      "我已选齐各住宿段酒店，请保留已确认条件，按这些酒店统一规划每天行程：\n" +
      rows
        .map(
          (row, index) =>
            `${row.city} ${row.check_in}→${row.check_out}：${picked[index]!.hotel_name}`,
        )
        .join("\n") +
      "\n每晚回到当晚所选酒店；先安排时间与交通缓冲，再按相邻项目结束时间查询路线，校验通过后展示草稿供我确认保存。",
  };
}

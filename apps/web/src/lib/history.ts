/** Merge server-owned turns by run ID; old pages cannot erase newer streamed results. */
import type { HistoricalRun, Run } from "./api";

export function mergeHistory(
  previous: HistoricalRun[],
  incoming: HistoricalRun[],
  sessionId: string,
): HistoricalRun[] {
  const rows = new Map<string, HistoricalRun>();
  for (const row of [...previous, ...incoming]) {
    if (row.session_id !== sessionId)
      throw new Error("历史记录不属于当前旅行。");
    const stored = rows.get(row.run_id);
    rows.set(row.run_id, { ...row, ...mergeRun(stored, row) });
  }
  return [...rows.values()].sort(
    (first, second) =>
      Date.parse(first.created_at) - Date.parse(second.created_at) ||
      (first.run_id < second.run_id
        ? -1
        : first.run_id === second.run_id
          ? 0
          : 1),
  );
}

export function mergeRun(previous: Run | undefined, incoming: Run): Run {
  if (
    previous?.run_id === incoming.run_id &&
    incoming.last_sequence < previous.last_sequence
  )
    return previous;
  if (
    [
      "实时回复仅供本轮查看；行程引用已保存，详情按需更新。",
      "实时回复仅供本轮查看；详情按需更新。",
    ].includes(incoming.answer)
  )
    return { ...incoming, answer: "该轮回答在旧版本中未保存。" };
  return incoming;
}

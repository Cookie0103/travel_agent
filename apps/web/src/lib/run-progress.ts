/** User-visible steps come only from persisted tool events, never model reasoning. */
import type { AppEvent } from "./api.ts";
import { toolCompletionState } from "./external-status.ts";
import { toolLabel } from "../components/tool-names.ts";

type Entry =
  | {
      type: "tool";
      key: string;
      name: string | null;
      state:
        | "running"
        | "ok"
        | "failed"
        | "correcting"
        | "unknown"
        | "needs_adjustment";
      code: string | null;
      reason: string | null;
      external?: AppEvent["external"];
    }
  | { type: "compacted" | "presentation"; key: string };

export function activityEntries(
  events: AppEvent[],
  status = "running",
): Entry[] {
  const entries: Entry[] = [];
  const open = new Map<string, Extract<Entry, { type: "tool" }>>();
  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
    if (event.kind === "tool_started") {
      const entry: Extract<Entry, { type: "tool" }> = {
        type: "tool",
        key: `s${event.sequence}`,
        name: event.tool_name,
        state: "running",
        code: null,
        reason: null,
      };
      entries.push(entry);
      if (event.tool_call_id) open.set(event.tool_call_id, entry);
    } else if (event.kind === "tool_finished") {
      const entry = event.tool_call_id
        ? open.get(event.tool_call_id)
        : undefined;
      const result = {
        state: toolCompletionState(event.code, event.external),
        code: event.code,
        reason: event.reason ?? null,
        external: event.external,
      };
      if (entry) Object.assign(entry, result);
      else
        entries.push({
          type: "tool",
          key: `f${event.sequence}`,
          name: event.tool_name,
          ...result,
        });
      if (event.tool_call_id) open.delete(event.tool_call_id);
    } else if (event.kind === "context_compacted")
      entries.push({ type: "compacted", key: `c${event.sequence}` });
    else if (event.kind === "presentation")
      entries.push({ type: "presentation", key: `p${event.sequence}` });
  }
  if (!["running", "cancelling"].includes(status))
    for (const entry of entries) {
      if (entry.type !== "tool") continue;
      if (entry.state === "running") entry.state = "unknown";
      else if (entry.state === "correcting") entry.state = "needs_adjustment";
    }
  return entries;
}

export function progressMessage(
  entries: Entry[],
  status: string,
): string | undefined {
  if (status === "cancelling") return "正在停止本轮处理…";
  if (status !== "running") return undefined;
  const current = entries.findLast(
    (entry) => entry.type === "tool" && entry.state === "running",
  );
  return current?.type === "tool"
    ? `正在${toolLabel(current.name)}…`
    : entries.length
      ? "正在整理结果和下一步…"
      : "正在理解你的需求…";
}

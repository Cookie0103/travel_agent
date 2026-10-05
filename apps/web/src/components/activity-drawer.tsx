/** Tool-call inspector built only from persisted run events; argument values are never shown. */
"use client";
import type { AppEvent } from "@/lib/api";
import { toolLabel } from "./tool-names";

type Entry =
  | {
      type: "tool";
      key: string;
      name: string | null;
      keys: string[];
      state: "running" | "ok" | "failed";
      code: string | null;
    }
  | { type: "compacted"; key: string }
  | { type: "presentation"; key: string };

export function activityEntries(events: AppEvent[]): Entry[] {
  const entries: Entry[] = [];
  const open = new Map<string, Extract<Entry, { type: "tool" }>>();
  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
    if (event.kind === "tool_started") {
      const entry: Extract<Entry, { type: "tool" }> = {
        type: "tool",
        key: `s${event.sequence}`,
        name: event.tool_name,
        keys: event.argument_keys,
        state: "running",
        code: null,
      };
      entries.push(entry);
      if (event.tool_call_id) open.set(event.tool_call_id, entry);
    } else if (event.kind === "tool_finished") {
      const entry = event.tool_call_id
        ? open.get(event.tool_call_id)
        : undefined;
      const state = event.code ? "failed" : "ok";
      if (entry) Object.assign(entry, { state, code: event.code });
      else
        entries.push({
          type: "tool",
          key: `f${event.sequence}`,
          name: event.tool_name,
          keys: event.argument_keys,
          state,
          code: event.code,
        });
    } else if (event.kind === "context_compacted")
      entries.push({ type: "compacted", key: `c${event.sequence}` });
    else if (event.kind === "presentation")
      entries.push({ type: "presentation", key: `p${event.sequence}` });
  }
  return entries;
}

export const toolCallCount = (events: AppEvent[]) =>
  events.filter((event) => event.kind === "tool_started").length;

export function RunSteps({ events }: { events: AppEvent[] }) {
  const entries = activityEntries(events);
  if (!entries.length) return null;
  return (
    <details className="run-steps">
      <summary>执行了 {toolCallCount(events)} 步 ▸</summary>
      <ol>
        {entries.map((entry) => (
          <li key={entry.key}>
            {entry.type === "tool"
              ? `${entry.state === "ok" ? "✓" : entry.state === "failed" ? "✗" : "●"} ${toolLabel(entry.name)}`
              : entry.type === "compacted"
                ? "上下文已压缩"
                : "已更新卡片"}
          </li>
        ))}
      </ol>
    </details>
  );
}

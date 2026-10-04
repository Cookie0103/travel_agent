/** Tool-call inspector built only from persisted run events; argument values are never shown. */
"use client";
import type { AppEvent } from "@/lib/api";
import type { Workspace } from "./workbench";
import { runStatus } from "./conversation";
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

export function ActivityDrawer({
  workspace,
  close,
}: {
  workspace: Workspace;
  close: () => void;
}) {
  const { run } = workspace;
  const entries = activityEntries(workspace.events);
  return (
    <aside
      className="activity-drawer"
      aria-label="Agent 活动"
      onKeyDown={(event) => {
        if (event.key === "Escape") close();
      }}
    >
      <div className="panel-head">
        <h2>Agent 活动</h2>
        <button aria-label="关闭 Agent 活动" onClick={close} autoFocus>
          ×
        </button>
      </div>
      {run ? (
        <p className="small muted">
          {run.mode === "live" ? "实时模型" : "离线演示"} ·{" "}
          {runStatus(run.status)}
        </p>
      ) : (
        <p className="small muted">还没有运行记录。</p>
      )}
      <ol className="activity-list">
        {entries.map((entry) => {
          if (entry.type === "compacted")
            return (
              <li key={entry.key} className="activity-divider">
                上下文已压缩
              </li>
            );
          if (entry.type === "presentation")
            return (
              <li key={entry.key} className="activity-note">
                已更新卡片
              </li>
            );
          return (
            <li key={entry.key} className={`activity-tool is-${entry.state}`}>
              <span className="activity-state" aria-hidden="true">
                {entry.state === "ok"
                  ? "✓"
                  : entry.state === "failed"
                    ? "✗"
                    : "●"}
              </span>
              <div>
                <strong>{toolLabel(entry.name)}</strong>
                <span className="sr-only">
                  {entry.state === "ok"
                    ? "完成"
                    : entry.state === "failed"
                      ? "失败"
                      : "进行中"}
                </span>
                {entry.code && (
                  <span className="error small"> {entry.code}</span>
                )}
                {!!entry.keys.length && (
                  <div className="chips-inline">
                    {entry.keys.map((key) => (
                      <span className="tag" key={key}>
                        {key}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {!entries.length && run && (
        <p className="small muted">本次运行没有工具调用。</p>
      )}
    </aside>
  );
}

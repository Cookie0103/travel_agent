/** Tool-call inspector built only from persisted run events; argument values are never shown. */
"use client";
import type { AppEvent } from "@/lib/api";
import { toolLabel } from "./tool-names";
import { errorExplanation } from "@/lib/error-explanation";
import { activityEntries, progressMessage } from "@/lib/run-progress";

export function RunSteps({
  events,
  status,
}: {
  events: AppEvent[];
  status: string;
}) {
  const entries = activityEntries(events, status);
  const message = progressMessage(entries, status);
  const tools = entries.filter((entry) => entry.type === "tool");
  if (!entries.length && !message) return null;
  return (
    <div className="run-progress" aria-label="执行进度">
      {message && (
        <div className="live-progress">
          <p className="step">{message}</p>
          <ol aria-label="最近执行步骤">
            {tools.slice(-3).map((entry) => (
              <li key={entry.key}>
                <span aria-hidden="true">
                  {entry.state === "ok"
                    ? "✓"
                    : entry.state === "failed"
                      ? "✗"
                      : "●"}{" "}
                </span>
                {toolLabel(entry.name)} ·{" "}
                {entry.state === "ok"
                  ? "已完成"
                  : entry.state === "failed"
                    ? "未完成"
                    : entry.state === "correcting"
                      ? "查询参数需调整"
                      : status === "cancelling"
                        ? "等待停止"
                        : "进行中"}
              </li>
            ))}
          </ol>
        </div>
      )}
      {entries.length > 0 && (
        <details className="run-steps">
          <summary>
            查看本轮执行记录（当前保留 {tools.length} 个工具步骤）
          </summary>
          <ol>
            {entries.map((entry) => (
              <li key={entry.key}>
                {entry.type === "tool"
                  ? `${entry.state === "ok" ? "✓" : entry.state === "failed" ? "✗" : "●"} ${toolLabel(entry.name)}${entry.state === "unknown" ? " — 未收到完成状态" : entry.state === "needs_adjustment" ? " — 该次查询参数需要调整" : entry.state === "failed" || entry.state === "correcting" ? ` — ${errorExplanation(entry.code, entry.reason, entry.external)}` : ""}`
                  : entry.type === "compacted"
                    ? "上下文已压缩"
                    : "已更新卡片"}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}

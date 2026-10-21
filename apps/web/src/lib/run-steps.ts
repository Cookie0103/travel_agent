/** Pure model of a run's tool steps, built only from run events (argument values are never read). */
import type { AppEvent } from "./api";
import { errorExplanation } from "./error-explanation.ts";
import { toolCompletionState } from "./external-status.ts";
import { toolLabel } from "../components/tool-names.ts";

/** Upper bound of events kept for the current run; a full planning run is well below this. */
export const EVENT_CAP = 500;

/**
 * Append a streamed event: replays of the same (run, sequence) are ignored, and only the
 * oldest events beyond EVENT_CAP are dropped so a long run never loses early steps.
 */
export function appendEvent(old: AppEvent[], event: AppEvent): AppEvent[] {
  const run = event.context?.run_id;
  if (
    old.some((e) => e.sequence === event.sequence && e.context?.run_id === run)
  )
    return old;
  const next = [...old, event];
  return next.length > EVENT_CAP ? next.slice(next.length - EVENT_CAP) : next;
}

export type StepState =
  "running" | "ok" | "failed" | "correcting" | "interrupted";

export type ToolStep = {
  type: "tool";
  key: string;
  name: string | null;
  state: StepState;
  code: AppEvent["code"];
  reason: AppEvent["reason"];
  external?: AppEvent["external"];
  /** Server time (ms) the call started; null when the event has no usable occurred_at. */
  startedAt: number | null;
  /** Whole seconds between start and finish, only when both server timestamps exist. */
  durationSeconds: number | null;
};
export type Step =
  | ToolStep
  | { type: "compacted"; key: string }
  | { type: "presentation"; key: string };

const time = (event: AppEvent): number | null => {
  const ms = event.occurred_at ? Date.parse(event.occurred_at) : NaN;
  return Number.isFinite(ms) ? ms : null;
};

/**
 * Ordered, de-duplicated steps. Sorted by sequence; the same sequence or the same
 * tool_call_id started twice is one step (replays). A retry has a new tool_call_id, so a
 * failed step is never replaced by its successful retry. A finish without a start is its
 * own row. With `settled`, steps still open are shown as interrupted and provisional
 * ("correcting") ones as failed, so a terminal run has only ✓/✗ rows.
 */
export function buildSteps(
  events: AppEvent[],
  options: { settled?: boolean } = {},
): Step[] {
  const steps: Step[] = [];
  const open = new Map<string, ToolStep>();
  const seen = new Set<number>();
  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
    if (seen.has(event.sequence)) continue;
    seen.add(event.sequence);
    if (event.kind === "tool_started") {
      if (event.tool_call_id && open.has(event.tool_call_id)) continue;
      const step: ToolStep = {
        type: "tool",
        key: `s${event.sequence}`,
        name: event.tool_name,
        state: "running",
        code: null,
        reason: null,
        startedAt: time(event),
        durationSeconds: null,
      };
      steps.push(step);
      if (event.tool_call_id) open.set(event.tool_call_id, step);
    } else if (event.kind === "tool_finished") {
      const state = toolCompletionState(event.code, event.external);
      const step = event.tool_call_id
        ? open.get(event.tool_call_id)
        : undefined;
      if (step) {
        const end = time(event);
        Object.assign(step, {
          state,
          code: event.code,
          reason: event.reason ?? null,
          external: event.external,
          durationSeconds:
            step.startedAt !== null && end !== null && end >= step.startedAt
              ? Math.round((end - step.startedAt) / 1000)
              : null,
        });
      } else
        steps.push({
          type: "tool",
          key: `f${event.sequence}`,
          name: event.tool_name,
          state,
          code: event.code,
          reason: event.reason ?? null,
          external: event.external,
          startedAt: null,
          durationSeconds: null,
        });
    } else if (event.kind === "context_compacted")
      steps.push({ type: "compacted", key: `c${event.sequence}` });
    else if (event.kind === "presentation")
      steps.push({ type: "presentation", key: `p${event.sequence}` });
  }
  if (options.settled)
    for (const step of steps)
      if (step.type === "tool") {
        if (step.state === "running") step.state = "interrupted";
        else if (step.state === "correcting") step.state = "failed";
      }
  return steps;
}

/** The summary count: one per tool_started event; a replay (same sequence or tool_call_id) counts once. */
export function stepCount(events: AppEvent[]): number {
  return new Set(
    events
      .filter((e) => e.kind === "tool_started")
      .map((e) => e.tool_call_id ?? `seq${e.sequence}`),
  ).size;
}

/** Whole seconds elapsed since a server start time; null without one. Clock skew never goes negative. */
export function elapsedSeconds(startedAt: number | null, now: number) {
  return startedAt === null
    ? null
    : Math.max(0, Math.floor((now - startedAt) / 1000));
}

export type StepLine = {
  mark: "✓" | "●" | "✗";
  text: string;
  /** Running steps only: elapsed seconds, rendered separately so assistive tech is not told every tick. */
  seconds: number | null;
};

/** Full display string, e.g. "估算路线 · 进行中 · 12 秒". */
export const lineText = (line: StepLine) =>
  line.seconds === null ? line.text : `${line.text} · ${line.seconds} 秒`;

/** Display line of one tool step; `now` (ms) only matters for running steps. */
export function toolLine(step: ToolStep, now: number): StepLine {
  const label = toolLabel(step.name);
  const explanation = () =>
    errorExplanation(step.code, step.reason, step.external);
  switch (step.state) {
    case "ok":
      return {
        mark: "✓",
        text: `${label} · 已完成${step.durationSeconds ? ` · ${step.durationSeconds} 秒` : ""}`,
        seconds: null,
      };
    case "failed":
      return {
        mark: "✗",
        text: `${label} · 失败 — ${explanation()}`,
        seconds: null,
      };
    case "interrupted":
      return { mark: "✗", text: `${label} · 已中断`, seconds: null };
    case "correcting":
      return {
        mark: "●",
        text: `${label} · 修正参数重试中 — ${explanation()}`,
        seconds: null,
      };
    default:
      return {
        mark: "●",
        text: `${label} · 进行中`,
        seconds: elapsedSeconds(step.startedAt, now),
      };
  }
}

/**
 * Where the steps go: "live" while the run is active; "folded" under the answer once it
 * ended normally with an answer; "expanded" (stopping at the failing step) when it failed,
 * was cancelled, or ended without a normal answer.
 */
export function stepsPlacement(run: {
  status: string;
  answer?: string | null;
  guided?: boolean;
}): "live" | "folded" | "expanded" {
  if (run.status === "running" || run.status === "cancelling") return "live";
  if (
    !run.answer ||
    run.guided ||
    run.status === "failed" ||
    run.status === "cancelled"
  )
    return "expanded";
  return "folded";
}

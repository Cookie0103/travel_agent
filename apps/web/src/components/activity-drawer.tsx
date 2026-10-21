/** Run progress built only from run events: a live list while running, folded under the answer afterwards. */
"use client";
import { useEffect, useState } from "react";
import type { AppEvent } from "@/lib/api";
import { buildSteps, stepCount, toolLine, type Step } from "@/lib/run-steps";

/** Wall clock that ticks once a second only while `active`; stops on unmount or when inactive. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const refresh = () => setNow(Date.now());
    const first = setTimeout(refresh, 0);
    const timer = setInterval(refresh, 1000);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [active]);
  return now;
}

function Row({ step, now }: { step: Step; now: number }) {
  if (step.type !== "tool")
    return (
      <li className="step-extra">
        {step.type === "compacted" ? "上下文已压缩" : "已更新卡片"}
      </li>
    );
  const line = toolLine(step, now);
  return (
    <li className={`step-row step-${step.state}`}>
      {step.state === "running" ? (
        <span aria-hidden="true" className="step-dot" />
      ) : (
        <span aria-hidden="true" className="step-mark">
          {line.mark}
        </span>
      )}
      <span>{line.text}</span>
      {line.seconds !== null ? (
        <span aria-hidden="true"> · {line.seconds} 秒</span>
      ) : null}
    </li>
  );
}

function StepList({ steps, settled }: { steps: Step[]; settled: boolean }) {
  const ticking =
    !settled &&
    steps.some(
      (s) => s.type === "tool" && s.state === "running" && s.startedAt !== null,
    );
  const now = useNow(ticking);
  return (
    <ol className="step-list" aria-live={settled ? undefined : "polite"}>
      {steps.map((step) => (
        <Row key={step.key} step={step} now={now} />
      ))}
    </ol>
  );
}

/** Visible, never-collapsed list for an active run, or a run that ended without an answer. */
export function RunStepList({
  events,
  settled = false,
}: {
  events: AppEvent[];
  settled?: boolean;
}) {
  const steps = buildSteps(events, { settled });
  if (!steps.length) return null;
  return (
    <div className="run-live">
      <StepList steps={steps} settled={settled} />
    </div>
  );
}

/** Collapsed summary under a finished answer; the user's open/closed state is not carried to the next run. */
export function RunSteps({ events }: { events: AppEvent[] }) {
  const steps = buildSteps(events, { settled: true });
  if (!steps.length) return null;
  return (
    <details className="run-steps">
      <summary>执行了 {stepCount(events)} 步 ▸</summary>
      <StepList steps={steps} settled />
    </details>
  );
}

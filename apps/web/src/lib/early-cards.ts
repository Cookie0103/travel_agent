import type { Choice, Hotels, Run } from "./api";
/** Only persisted presentation events (ids or private offers) may trigger early card reads. */
export function isCardEvent(event: {
  kind: string;
  presentation?: unknown;
}): boolean {
  const data = (event.presentation as { data?: unknown } | undefined)?.data;
  return event.kind === "presentation" && typeof data === "object" && !!data;
}

export type RunBinding = Pick<Run, "session_id" | "run_id">;
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
export function belongsToRun(event: unknown, binding: RunBinding): boolean {
  if (!record(event) || !record(event.context)) return false;
  return matchesRun(event.context, binding);
}

/** Only historical choices need PG answered/stale state; this never re-fetches supplier facts. */
export function historicalChoiceEvents(
  runs: Run[],
): { event: { context?: unknown; presentation?: unknown }; run: Run }[] {
  return runs.flatMap((run) =>
    (run.presentations ?? [])
      .filter(
        (event) =>
          belongsToRun(event, run) &&
          record(event.presentation) &&
          record(event.presentation.data) &&
          event.presentation.data.component === "choice",
      )
      .map((event) => ({ event, run })),
  );
}
export function runCards(run: Run): {
  hotels?: Hotels;
  draftId?: string;
  planId?: string;
  choices?: Choice[];
} {
  const result: {
    hotels?: Hotels;
    draftId?: string;
    planId?: string;
    choices?: Choice[];
  } = {};
  for (const event of run.presentations ?? []) {
    if (
      !belongsToRun(event, run) ||
      !record(event.presentation) ||
      !record(event.presentation.data)
    )
      continue;
    const data = event.presentation.data;
    if (
      data.component === "choice" &&
      data.source_run_id === run.run_id &&
      data.session_id === run.session_id &&
      typeof data.choice_id === "string"
    ) {
      result.choices ??= [];
      if (!result.choices.some((card) => card.choice_id === data.choice_id))
        result.choices.push(data as Choice);
    }
    if (data.component === "hotel_comparison") result.hotels = data as Hotels;
    if (typeof data.draft_id === "string" && data.draft_id)
      result.draftId = data.draft_id;
    else if (typeof data.plan_id === "string" && data.plan_id)
      result.planId = data.plan_id;
  }
  return result;
}

export function matchesRun(value: unknown, binding: RunBinding): boolean {
  return (
    record(value) &&
    value.session_id === binding.session_id &&
    value.run_id === binding.run_id
  );
}

export function hotelsForRun(
  run: Run,
  cached?: Hotels,
  origin?: RunBinding,
): Hotels | undefined {
  return cached && matchesRun(origin, run) ? cached : runCards(run).hotels;
}

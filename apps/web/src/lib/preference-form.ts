/** Pure rules for the preference editor: dirty detection and fact grouping. */
import type { components } from "./api-types";
import { memoryStatuses, type MemoryFact } from "./memory.ts";

type Preferences = components["schemas"]["Preferences"];
type PreferenceForm = {
  interests: string;
  constraints: string;
  transport: Preferences["transport"];
};

export const preferenceLines = (text: string) =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

const same = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((value, index) => value === b[index]);

/** True when the form holds edits that differ from the last saved server values. */
export function isDirty(
  saved:
    | Pick<Preferences, "interests" | "soft_constraints" | "transport">
    | undefined,
  form: PreferenceForm,
) {
  if (!saved) return false;
  return (
    !same(preferenceLines(form.interests), saved.interests ?? []) ||
    !same(preferenceLines(form.constraints), saved.soft_constraints ?? []) ||
    form.transport !== (saved.transport ?? null)
  );
}

/** current: applies to this trip; elsewhere: another trip's temporary facts; history: no longer in force. */
export function factGroups(facts: readonly MemoryFact[], sessionId: string) {
  const live = (fact: MemoryFact) =>
    fact.status === "active" || fact.status === "proposed";
  const here = (fact: MemoryFact) =>
    fact.scope === "long_term" || fact.session_id === sessionId;
  return {
    current: facts.filter((fact) => live(fact) && here(fact)),
    elsewhere: facts.filter((fact) => live(fact) && !here(fact)),
    history: facts.filter((fact) => !live(fact)),
  };
}

export const factStatus = (fact: MemoryFact, sessionId: string) =>
  fact.status === "active" &&
  fact.scope === "trip" &&
  fact.session_id !== sessionId
    ? "仅用于其他旅行"
    : memoryStatuses[fact.status];

/** Pure rules for the preference list: fact grouping and status labels. */
import { memoryStatuses, type MemoryFact } from "./memory.ts";

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

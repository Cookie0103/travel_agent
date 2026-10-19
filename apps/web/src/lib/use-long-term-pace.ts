/** Long-term pace from the same /memory rows the preference panel reads; no new backend field. */
"use client";
import { useEffect, useState } from "react";
import { api, type Identity } from "./api";
import type { MemoryFact } from "./memory";
import { longTermPace, type Pace } from "./pace";

export function useLongTermPace(
  identity: Pick<Identity, "session_id" | "token"> | undefined,
  refreshKey: string,
): Pace | "" {
  const [state, setState] = useState<{ token: string; pace: Pace | "" }>();
  const token = identity?.token;
  useEffect(() => {
    if (!token) return;
    let active = true;
    api<MemoryFact[]>("/memory", token)
      .then((facts) => active && setState({ token, pace: longTermPace(facts) }))
      .catch(() => active && setState({ token, pace: "" }));
    return () => {
      active = false;
    };
  }, [token, refreshKey]);
  return state && state.token === token ? state.pace : "";
}

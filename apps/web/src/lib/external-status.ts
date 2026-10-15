/** Closed transport metadata keeps a pending parameter correction visible without a failure badge. */
import type { AppEvent } from "./api";

export function toolCompletionState(
  code: AppEvent["code"],
  external: AppEvent["external"],
): "correcting" | "failed" | "ok" {
  return external?.provisional ? "correcting" : code ? "failed" : "ok";
}

/** Which recovery buttons an error banner offers, decided by where the error came from. */
import { ApiError } from "./api.ts";

export type ErrorKind = "stream" | "conflict" | "validation" | "run" | "other";

export function classifyError(failure: unknown): ErrorKind {
  if (failure instanceof ApiError) {
    if (failure.status === 409) return "conflict";
    if (failure.status === 422) return "validation";
  }
  return "other";
}

/** A failure raised while following the event stream is a stream error whatever its status code. */
export function errorKindFor(
  failure: unknown,
  streamFailure: boolean,
): ErrorKind {
  return streamFailure ? "stream" : classifyError(failure);
}

export function errorActions(kind: ErrorKind, runActive: boolean) {
  return {
    refresh: kind !== "validation",
    reconnect: kind === "stream" && runActive,
  };
}

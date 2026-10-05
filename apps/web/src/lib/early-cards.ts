/** Only persisted presentation events (ids or private offers) may trigger early card reads. */
export function isCardEvent(event: {
  kind: string;
  presentation?: unknown;
}): boolean {
  const data = (event.presentation as { data?: unknown } | undefined)?.data;
  return event.kind === "presentation" && typeof data === "object" && !!data;
}

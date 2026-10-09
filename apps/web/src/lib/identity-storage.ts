/** Persist only the active identity; unresolved messages belong to this tab and trip. */
import type { Identity } from "./api";

type Storage = Pick<
  globalThis.Storage,
  "getItem" | "setItem" | "removeItem" | "length" | "key"
>;
const IDENTITY = "travel-demo-v2";
const OUTBOX = "travel-message-outbox-v1:";
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string =>
  typeof value === "string" && !!value;
function parse(value: string | null): unknown {
  try {
    return value ? JSON.parse(value) : undefined;
  } catch {
    return undefined;
  }
}
function pending(value: unknown): Identity["pending_message"] {
  if (
    !record(value) ||
    !text(value.client_message_id) ||
    !text(value.text) ||
    !["offline", "deepseek", "claude"].includes(String(value.mode))
  )
    return undefined;
  return {
    client_message_id: value.client_message_id,
    text: value.text,
    mode: value.mode as NonNullable<Identity["pending_message"]>["mode"],
  };
}
export function pendingFor(
  tab: Storage,
  identity: Pick<Identity, "token" | "session_id">,
): Identity["pending_message"] {
  const value = parse(tab.getItem(OUTBOX + identity.session_id));
  if (
    !record(value) ||
    value.token !== identity.token ||
    value.session_id !== identity.session_id
  )
    return undefined;
  return pending(value.message);
}
export function persistIdentity(
  local: Storage,
  tab: Storage,
  identity: Identity,
): void {
  local.setItem(
    IDENTITY,
    JSON.stringify({ token: identity.token, session_id: identity.session_id }),
  );
  const key = OUTBOX + identity.session_id;
  if (identity.pending_message)
    tab.setItem(
      key,
      JSON.stringify({
        token: identity.token,
        session_id: identity.session_id,
        message: identity.pending_message,
      }),
    );
  else tab.removeItem(key);
}
export function restoreIdentity(
  local: Storage,
  tab: Storage,
): Identity | undefined {
  const value = parse(local.getItem(IDENTITY));
  if (!record(value) || !text(value.token) || !text(value.session_id)) {
    local.removeItem(IDENTITY);
    return undefined;
  }
  const identity: Identity = {
    token: value.token,
    session_id: value.session_id,
    // Legacy references are usable only in this first migration read, never persisted again.
    ...(text(value.plan_id) ? { plan_id: value.plan_id } : {}),
    ...(text(value.run_id) ? { run_id: value.run_id } : {}),
  };
  const message = pendingFor(tab, identity) ?? pending(value.pending_message);
  if (message) identity.pending_message = message;
  persistIdentity(local, tab, identity);
  return identity;
}
export function forgetIdentity(
  local: Storage,
  tab: Storage,
  token?: string,
): void {
  const value = parse(local.getItem(IDENTITY));
  const owner =
    token ?? (record(value) && text(value.token) ? value.token : undefined);
  if (owner) {
    for (let index = tab.length - 1; index >= 0; index--) {
      const key = tab.key(index);
      if (!key?.startsWith(OUTBOX)) continue;
      const outbox = parse(tab.getItem(key));
      if (record(outbox) && outbox.token === owner) tab.removeItem(key);
    }
  }
  if (record(value) && value.token === owner) local.removeItem(IDENTITY);
}

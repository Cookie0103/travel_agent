/** Shared HTTP and persisted SSE reader; reconnects only read, never repeat a message. */
import type { components } from "./api-types";
import type { HotelSelection } from "./hotel-groups";
import type { Mode } from "./models";
export type RequestState = components["schemas"]["RequestView"];
export type Run = components["schemas"]["RunView"];
export type HistoricalRun = components["schemas"]["HistoricalRun"];
type RunPage = components["schemas"]["RunPage"];
export type Plan = components["schemas"]["UiPlanView"];
export type Article = components["schemas"]["Article"];
export type Hotels = components["schemas"]["UiHotelPresentation"];
export type Booking = components["schemas"]["Booking"];
export type Choice = components["schemas"]["ChoiceCard"];
export type MessageSelection =
  | HotelSelection
  | {
      expected_revision: number;
      selection: components["schemas"]["ChoiceSelection"];
    };
export type AppEvent = components["schemas"]["UiRuntimeEvent"] & {
  sequence: number;
};
export type Identity = {
  token: string;
  session_id: string;
  run_id?: string;
  plan_id?: string;
  pending_message?: components["schemas"]["MessageInput"];
};

export class ApiError extends Error {
  readonly status: number;
  /** 后端 {code,message} 的封闭错误码；非业务错误（代理/网络）没有。 */
  readonly code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/** 后端统一 {code,message}（含请求校验错误）；其余情况用通用文案。 */
function apiError(status: number, body: unknown, fallback?: string) {
  const data = (body ?? {}) as { code?: unknown; message?: unknown };
  const code = typeof data.code === "string" ? data.code : undefined;
  if (typeof data.message === "string" && data.message)
    return new ApiError(data.message, status, code);
  return new ApiError(fallback ?? `请求失败（${status}）`, status, code);
}

export function sourceHref(value: string): string | undefined {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export function readWhile(active: () => boolean) {
  return async <T>(request: Promise<T>): Promise<T> => {
    const value = await request;
    if (!active()) throw new Error("会话已改变，忽略原请求结果。");
    return value;
  };
}

export function messageInput(
  previous: Identity["pending_message"],
  text: string,
  mode: Mode,
  selection?: MessageSelection,
): components["schemas"]["MessageInput"] {
  if (
    previous &&
    (previous.text !== text ||
      previous.mode !== mode ||
      (selection &&
        JSON.stringify([
          previous.expected_revision,
          previous.hotel_stays,
          previous.selection,
        ]) !==
          JSON.stringify([
            selection.expected_revision,
            "hotel_stays" in selection ? selection.hotel_stays : undefined,
            "selection" in selection ? selection.selection : undefined,
          ])))
  )
    throw new Error(
      "上一条消息的响应尚未核对，请先重试原消息；会保留同一个去重ID。",
    );
  return (
    previous ?? {
      client_message_id: crypto.randomUUID(),
      text,
      mode,
      ...selection,
    }
  );
}

export async function readDraft(draftId: string, token: string): Promise<Plan> {
  const draft = await api<Plan>(`/plan-drafts/${draftId}`, token);
  return draft.status === "confirmed"
    ? api<Plan>(`/plans/${draft.plan_id}`, token)
    : draft;
}

export async function readConfirmedPlan(
  identity: Pick<Identity, "plan_id" | "token">,
): Promise<Plan | undefined> {
  return identity.plan_id
    ? api<Plan>(`/plans/${identity.plan_id}`, identity.token)
    : undefined;
}

/** A confirmation receipt is reported before the independent canonical read. */
export async function confirmPlan(
  draftId: string,
  token: string,
  onConfirmed: (saved: components["schemas"]["SavedPlan"]) => void,
): Promise<Plan> {
  const saved = await api<components["schemas"]["SavedPlan"]>(
    `/plan-drafts/${draftId}/confirm`,
    token,
    "POST",
  );
  onConfirmed(saved);
  try {
    return await api<Plan>(`/plans/${saved.plan_id}`, token);
  } catch (failure) {
    const explanation =
      "确认已成功，正式行程读取失败。请重新读取，无需再次保存。";
    if (failure instanceof ApiError)
      throw new ApiError(explanation, failure.status, failure.code);
    throw new Error(explanation);
  }
}

export type TripSummary = components["schemas"]["SessionSummary"];
type TripPage = components["schemas"]["SessionPage"];
export function createTrip(token: string) {
  return api<components["schemas"]["SessionView"]>("/sessions", token, "POST");
}
export async function readTripHistory(
  token: string,
  cursor?: string,
): Promise<TripPage> {
  const query = new URLSearchParams({ limit: "20" });
  if (cursor) query.set("cursor", cursor);
  try {
    return await api<TripPage>(`/sessions?${query}`, token);
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 404)
      throw new ApiError("当前服务版本暂不支持旅行历史。", 404);
    throw failure;
  }
}

export async function readRunHistory(
  identity: Pick<Identity, "session_id" | "token">,
  before?: string,
): Promise<RunPage> {
  const query = new URLSearchParams({ limit: "20" });
  if (before) query.set("before", before);
  return api<RunPage>(
    `/sessions/${identity.session_id}/runs?${query}`,
    identity.token,
  );
}

export async function api<T>(
  path: string,
  token?: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    throw apiError(response.status, await response.json().catch(() => null));
  }
  return response.json() as Promise<T>;
}

export async function readEvents(
  runId: string,
  token: string,
  after: number,
  signal: AbortSignal,
  receive: (event: AppEvent) => void,
): Promise<void> {
  const response = await fetch(`/api/runs/${runId}/events?after=${after}`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  });
  if (!response.ok) {
    throw apiError(
      response.status,
      await response.json().catch(() => null),
      "进度连接失败，可以重新连接读取已保存事件。",
    );
  }
  if (!response.body)
    throw new Error("进度连接失败，可以重新连接读取已保存事件。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder
        .decode(value, { stream: !done })
        .replaceAll("\r\n", "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const data = block
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (data) receive(JSON.parse(data) as AppEvent);
      }
      if (done) break;
    }
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}

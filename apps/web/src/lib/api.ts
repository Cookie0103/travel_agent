/** Shared HTTP and persisted SSE reader; reconnects only read, never repeat a message. */
import type { components } from "./api-types";
import type { Mode } from "./models";
export type RequestState = components["schemas"]["TravelRequest"];
export type Run = components["schemas"]["RunView"];
export type Plan = components["schemas"]["UiPlanView"];
export type Article = components["schemas"]["Article"];
export type Hotels = components["schemas"]["UiHotelPresentation"];
export type Booking = components["schemas"]["Booking"];
export type AppEvent = components["schemas"]["UiRuntimeEvent"] & {
  sequence: number;
};
export type Identity = components["schemas"]["DemoIdentity"] & {
  session_id: string;
  run_id?: string;
  plan_id?: string;
  pending_message?: components["schemas"]["MessageInput"];
};

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
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
): components["schemas"]["MessageInput"] {
  if (previous && (previous.text !== text || previous.mode !== mode))
    throw new Error(
      "上一条消息的响应尚未核对，请先重试原消息；会保留同一个去重ID。",
    );
  return previous ?? { client_message_id: crypto.randomUUID(), text, mode };
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
    const error = await response.json().catch(() => null);
    throw new ApiError(
      error?.message ||
        (response.status === 422
          ? "输入不符合条件，请检查日期、人数和金额。"
          : `请求失败（${response.status}）`),
      response.status,
    );
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
  if (!response.ok || !response.body)
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

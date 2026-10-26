/** SSE 连接状态机：流 EOF 只说明连接结束；是否结束由 /runs/{id} 的状态决定。 */
import { ApiError } from "./api.ts";

export const RECONNECT_LIMIT = 5;
const ACTIVE = ["running", "cancelling"];
export const isRunActive = (status: string) => ACTIVE.includes(status);
/** 第 n 次连续失败后的等待：500ms 起指数退避，上限 8s。 */
export const reconnectDelay = (failures: number) =>
  Math.min(500 * 2 ** (failures - 1), 8000);

type FollowOutcome = "terminal" | "exhausted" | "aborted";

/**
 * 读到运行终态为止：每次断开（EOF 或网络错误）都查状态，未终态则带已收到的
 * 最大 sequence 重连。游标有前进即重置失败预算；连续失败超限返回 exhausted，
 * 由界面提供手动重连。401/403/404 不重试，交给调用方处理。
 */
export async function followRun(options: {
  read: (after: number) => Promise<void>;
  cursor: () => number;
  status: () => Promise<{ status: string; last_sequence: number }>;
  wait: (ms: number) => Promise<void>;
  active: () => boolean;
  limit?: number;
}): Promise<FollowOutcome> {
  const limit = options.limit ?? RECONNECT_LIMIT;
  let failures = 0;
  while (options.active()) {
    const before = options.cursor();
    let state: Awaited<ReturnType<typeof options.status>> | undefined;
    try {
      await options.read(before);
      state = await options.status();
    } catch (failure) {
      if (!options.active()) return "aborted";
      if (
        failure instanceof ApiError &&
        [401, 403, 404].includes(failure.status)
      )
        throw failure;
      // 其他错误按断线处理：下面不做终态判断，直接退避重连。
    }
    if (!options.active()) return "aborted";
    if (
      state &&
      !isRunActive(state.status) &&
      options.cursor() >= state.last_sequence
    )
      return "terminal";
    failures = options.cursor() > before ? 0 : failures + 1;
    if (failures > limit) return "exhausted";
    await options.wait(reconnectDelay(Math.max(failures, 1)));
  }
  return "aborted";
}

export const MEMORY_POLL_MS = 3000;
export const MEMORY_POLL_LIMIT = 40; // 约2分钟；抽取在后台失败或进程重启时不无限轮询

/**
 * 运行终态后记忆仍在后台抽取（memory_pending）：低频查 /runs/{id}，
 * 把新追加的展示事件交给 hydrate，直到抽取结束、超出次数或界面不再关注本轮。
 */
export async function followMemory<
  T extends { memory_pending?: boolean | null; presentations?: unknown[] },
>(options: {
  initial: T;
  status: () => Promise<T>;
  wait: (ms: number) => Promise<void>;
  active: () => boolean;
  hydrate: (event: unknown, run: T) => Promise<void>;
  limit?: number;
}): Promise<void> {
  let seen = options.initial.presentations?.length ?? 0;
  let pending = options.initial.memory_pending === true;
  for (let i = 0; pending && i < (options.limit ?? MEMORY_POLL_LIMIT); i++) {
    await options.wait(MEMORY_POLL_MS);
    if (!options.active()) return;
    let run: T;
    try {
      run = await options.status();
    } catch {
      continue; // 记忆卡只是附加内容：查询失败不打断对话，下次再试
    }
    if (!options.active()) return;
    const events = run.presentations ?? [];
    // 展示事件按时间追加；只交出上次之后的新事件，避免重复补卡。
    for (const event of events.slice(Math.min(seen, events.length)))
      await options.hydrate(event, run);
    seen = events.length;
    pending = run.memory_pending === true;
  }
}

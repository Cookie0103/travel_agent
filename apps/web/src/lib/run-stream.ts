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

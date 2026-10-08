/** Application error codes have fixed explanations; arbitrary error text is never displayed. */
import type { AppEvent } from "./api";

type ErrorCode = NonNullable<AppEvent["code"]>;
const explanations: Record<ErrorCode, string> = {
  validation: "校验未通过：条件或修改不符合要求，请核对相关信息。",
  blocked: "操作受限：请检查操作前提或调用限制。",
  unavailable: "服务不可用：请稍后重试读取；此次失败不等于已保存数据丢失。",
  timeout: "响应超时：已完成的步骤仍保留；超时不代表密钥或额度有误。",
  rate_limited: "调用受限：请求过于频繁或达到限额，请稍后重试。",
  provider_error: "外部服务异常：本次未取得可用结果，请稍后重试。",
  conflict:
    "状态冲突：条件存在冲突或行程版本已变化，请核对条件并读取最新状态。",
  cancelled: "已取消：已完成的步骤仍保留。",
};

export function errorExplanation(code: string | null | undefined): string {
  return code && Object.hasOwn(explanations, code)
    ? explanations[code as ErrorCode]
    : "原因暂不明确：请读取最新状态或稍后重试。";
}

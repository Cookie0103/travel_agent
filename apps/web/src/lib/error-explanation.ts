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

type ToolReason = NonNullable<AppEvent["reason"]>;
/** Closed reason codes recorded by the backend; "other" and unknown values fall back to the code text. */
const reasons: Record<Exclude<ToolReason, "other">, string> = {
  tool_call_cap: "本轮工具调用次数已用完，请把剩余需求拆成下一条消息继续",
  repair_limit: "行程校验的修复次数已用完",
  repeat_blocked: "相同请求已被拒绝，未重复执行",
  result_too_long: "结果过长未能返回，请缩小查询范围",
  unregistered_tool: "调用了不存在的工具，已拒绝",
  context_reuse: "工具调用不属于当前执行，已拒绝",
  evidence_missing: "引用的证据不存在或不属于当前旅行，请重新查询后再校验",
  offer_unknown_id: "引用的酒店报价不存在，请重新查询",
  not_found: "引用的会话、草稿或行程不存在",
  live_hold_disabled: "实时酒店只支持查询和乐天链接，不能暂留",
  plan_exists: "已有正式行程，请基于它做局部修改",
  patch_invalid: "修改引用了不存在或已锁定的行程项",
  revision_stale: "旅行条件已更新，请按最新条件重试",
  lodging_budget_conflict: "住宿预算下限超过全程预算，请确认以哪个为准",
  hotel_search_location_required: "目的地范围较大，请提供具体住宿城市或地点",
  schema: "工具参数格式不正确",
};

export function errorExplanation(
  code: string | null | undefined,
  reason?: string | null,
): string {
  // 工具原因码只解释工具级错误码；timeout/cancelled等运行级错误不借用它。
  if (
    (code === "blocked" || code === "validation") &&
    reason &&
    Object.hasOwn(reasons, reason)
  )
    return reasons[reason as keyof typeof reasons];
  return code && Object.hasOwn(explanations, code)
    ? explanations[code as ErrorCode]
    : "原因暂不明确：请读取最新状态或稍后重试。";
}

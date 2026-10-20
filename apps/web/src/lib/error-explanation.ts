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
/** Run-level reasons only appear on the final failed event; they are not tool reasons. */
const runReasons = {
  conversation_incomplete:
    "本轮在行程草稿完成前停止了；酒店等已完成的结果已保留。请再发一条消息，例如“继续排行程”。",
  conversation_state_unavailable: "对话状态暂时读取失败，请稍后重试",
  max_turns: "本轮对话轮数已用完，已完成的结果已保留；请再发一条消息继续",
  request_limit:
    "本轮模型请求次数已用完，已完成的结果已保留；请再发一条消息继续",
  request_too_large:
    "本轮上下文超过请求大小上限，已完成的结果已保留；请缩小本次需求后继续",
  budget_limit: "本地费用预算或授权检查未通过，执行已停止；请核对可用预算",
  local_guard:
    "本地执行保护已停止本轮，已完成的结果已保留；请读取最新状态后继续",
} as const;
/** Closed reason codes recorded by the backend; "other" and unknown values fall back to the code text. */
const reasons: Record<
  Exclude<ToolReason, "other" | keyof typeof runReasons>,
  string
> = {
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
  hotel_missing_fields: "酒店查询缺少必要条件，请在对话中补充",
  hotel_room_preferences_missing: "酒店房型偏好尚未确认，请在对话中说明",
  hotel_external_validation: "酒店查询条件不被数据源接受，请调整条件后重试",
  hotel_external_unavailable: "酒店数据源暂不可用，请稍后重试",
  hotel_selection_required: "请在每个住宿段选择一家酒店，选齐后再开始规划",
  hotel_api_unconfigured: "酒店数据源尚未配置，暂不能查询",
  schema: "工具参数格式不正确",
};

/** Server-written Chinese validation reason (e.g. unsupported demo scope); anything else is not echoed. */
function validationDetail(detail: string | null | undefined): string | null {
  const text = detail?.trim();
  return text &&
    text.length <= 60 &&
    /[\u4e00-\u9fff]/.test(text) &&
    !/[\r\n=]|:\/\//.test(text)
    ? text.replace(/[。.]$/, "")
    : null;
}

export function errorExplanation(
  code: string | null | undefined,
  reason?: string | null,
  external?: AppEvent["external"],
  detail?: string | null,
): string {
  if (external?.provisional) return "正在修正查询参数";
  if (!external) {
    const base = baseExplanation(code, reason);
    const specific = code === "validation" ? validationDetail(detail) : null;
    // 仅当没有更具体的封闭原因码时，才用服务端给出的校验原因替换笼统提示。
    return specific && base === explanations.validation
      ? `校验未通过：${specific}。`
      : base;
  }
  const kinds = {
    rate_limited: "供应商请求过于频繁",
    timeout: "供应商响应超时",
    network: "供应商网络连接失败",
    upstream_5xx: "供应商服务暂时异常",
    bad_request: "供应商拒绝请求参数或权限",
    not_found_empty: "供应商返回空结果",
    quota_exhausted: "供应商调用配额已用完",
    invalid_json: "供应商返回的数据格式无效",
  } as const;
  let message = external.kind
    ? kinds[external.kind]
    : baseExplanation(code, reason);
  if (external.status !== null) message += `（HTTP ${external.status}）`;
  if (external.used !== null && external.limit !== null)
    message += `；${external.cap_scope === "run" ? "本轮" : "今日"}已用${external.used}/${external.limit}次`;
  if (external.attempts > 1) message += `；已重试${external.attempts - 1}次`;
  if (external.retry_skipped)
    message += `；因${external.retry_skipped === "quota" ? "配额不足" : "剩余执行时间不足"}未执行重试`;
  if (external.waited_seconds > 0)
    message += `；已等待${external.waited_seconds.toFixed(1)}秒`;
  return message + "。请核对条件或稍后再试。";
}

function baseExplanation(
  code: string | null | undefined,
  reason?: string | null,
): string {
  if (
    (code === "blocked" || code === "unavailable") &&
    reason &&
    Object.hasOwn(runReasons, reason)
  )
    return runReasons[reason as keyof typeof runReasons];
  // 工具原因码只解释工具级错误码；timeout/cancelled等运行级错误不借用它。
  if (
    (code === "blocked" || code === "validation" || code === "unavailable") &&
    reason &&
    Object.hasOwn(reasons, reason)
  )
    return reasons[reason as keyof typeof reasons];
  return code && Object.hasOwn(explanations, code)
    ? explanations[code as ErrorCode]
    : "原因暂不明确：请读取最新状态或稍后重试。";
}

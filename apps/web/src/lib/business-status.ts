import type { Run } from "./api";
import { errorExplanation } from "./error-explanation.ts";
const runtimeLabels: Record<string, string> = {
  running: "处理中",
  cancelling: "取消中",
  completed: "完成",
  failed: "失败",
  cancelled: "已取消",
  partial: "部分完成",
  awaiting_user: "等你操作",
};
export const runStatus = (status: string): string =>
  Object.hasOwn(runtimeLabels, status) ? runtimeLabels[status] : "状态暂不明确";

export const runFailureMessage = (
  code: string | null | undefined,
  reason?: string | null,
): string => `执行未完成：${errorExplanation(code, reason)}`;

/** A completed reply is not proof of staging, validation or a formal commit. */
export function runLabel(run: Run): string {
  const result = run.business_result;
  let business: string;
  switch (result?.kind) {
    case "draft_staged":
      business =
        result.validation_status === "conflict"
          ? "草稿有校验冲突，不能确认"
          : result.validation_status === "complete"
            ? "草稿已校验，尚未保存"
            : "草稿已暂存，部分可校验，尚未保存";
      break;
    case "stage_failed":
      business = "草稿未生成";
      break;
    case "confirmed":
      business = `已确认行程 · V${result.version}`;
      break;
    case "answer_only":
      return run.status === "completed" ? "回复完成" : runStatus(run.status);
    default:
      return run.status === "completed"
        ? "回复结束，业务状态未提供"
        : runStatus(run.status);
  }
  return run.status === "completed"
    ? business
    : `${runStatus(run.status)} · ${business}`;
}

/** Reasons are server whitelist values; do not use a model answer as failure guidance. */
export function stageGuidance(run: Run) {
  const result = run.business_result;
  if (result?.kind !== "stage_failed") return undefined;
  switch (result.reason) {
    case "plan_exists":
      return {
        message:
          "这个旅行已有正式行程。可以说明要改的部分，在原行程上生成修改草稿；如果是另一趟旅行，请新建旅行。",
        existingPlan: true,
      };
    case "patch_invalid":
      return {
        message:
          "本次修改无法应用到现有行程，可能涉及已变化或锁定的项目。请先读取最新行程，再说明需要调整的部分。",
        existingPlan: false,
      };
    case "repair_limit":
      return {
        message:
          "本轮校验与修复次数已用完，草稿未生成。请缩小要改的范围，确认条件后再发起一轮规划。",
        existingPlan: false,
      };
    default:
      return {
        message:
          "本次未能生成草稿。请读取最新状态，查看执行步骤中的失败类别后再试。",
        existingPlan: false,
      };
  }
}

/** Partial answer text does not replace a trustworthy failure category. */
export function runErrorMessage(run: Run): string | undefined {
  return run.error_code && !stageGuidance(run)
    ? runFailureMessage(run.error_code)
    : undefined;
}

import type { Run } from "./api";
const runtimeLabels: Record<string, string> = {
  running: "处理中",
  cancelling: "取消中",
  completed: "完成",
  failed: "失败",
  cancelled: "已取消",
  partial: "部分完成",
  awaiting_user: "等你操作",
};
export const runStatus = (status: string) => runtimeLabels[status] ?? status;

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

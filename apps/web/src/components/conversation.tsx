/** Persisted conversation turns plus the latest run's streamed reply and current cards. */
"use client";
import type { Workspace } from "./workbench";
import { toolLabel } from "./tool-names";
import { HotelResults, planDays } from "./results";
import type { Mode } from "./composer";
import { RunSteps } from "./activity-drawer";
import { Markdown } from "./markdown";

const runStatusLabels: Record<string, string> = {
  running: "处理中",
  cancelling: "取消中",
  completed: "完成",
  failed: "失败",
  cancelled: "已取消",
  partial: "部分完成",
  awaiting_user: "等你操作",
};
export const runStatus = (status: string) => runStatusLabels[status] ?? status;

const presets = ["比较酒店", "生成行程", "修改第二天下午"];
const examples = [
  "京都三天两夜，2 个大人，预算 5 万日元，想看寺庙，少走路",
  "下雨天京都有哪些室内景点？",
  "帮我比较这几天京都的酒店",
];

function currentStep(workspace: Workspace): string | undefined {
  const finished = new Set(
    workspace.events
      .filter((event) => event.kind === "tool_finished")
      .map((event) => event.tool_call_id),
  );
  const open = workspace.events
    .filter(
      (event) =>
        event.kind === "tool_started" && !finished.has(event.tool_call_id),
    )
    .at(-1);
  return open ? toolLabel(open.tool_name) : undefined;
}

export function Welcome({ workspace }: { workspace: Workspace }) {
  return (
    <section className="welcome">
      <h1>想去哪里玩？</h1>
      <p>
        用一句话说出目的地、天数、人数、预算和偏好，我会比较酒店、检查行程，并在你确认后才保存。
      </p>
      <button
        className="primary"
        disabled={workspace.busy || workspace.restoring}
        onClick={() => void workspace.login()}
      >
        {workspace.restoring ? "正在恢复上次会话…" : "开始"}
      </button>
      <p className="muted small">
        实时规划支持日本国内；离线演示使用京都样本。
      </p>
    </section>
  );
}

export function Conversation({
  workspace,
  mode,
  send,
  fill,
  openPanel,
}: {
  workspace: Workspace;
  mode: Mode;
  send: (text: string, mode: Mode) => void;
  fill: (text: string) => void;
  openPanel: () => void;
}) {
  const { run } = workspace;
  const step = currentStep(workspace);
  const running =
    workspace.busy || ["running", "cancelling"].includes(run?.status ?? "");
  const noRevision = !workspace.request?.revision;
  const currentPrompt = workspace.history.find(
    (row) => row.run_id === run?.run_id,
  )?.prompt;
  return (
    <div className="conversation-stream" aria-live="polite">
      {workspace.restoring && <p role="status">正在恢复对话历史…</p>}
      {workspace.historyError && <p role="alert">{workspace.historyError}</p>}
      {workspace.historyBefore && (
        <button
          disabled={workspace.busy}
          onClick={() => void workspace.loadEarlier()}
        >
          加载更早对话
        </button>
      )}
      {!workspace.restoring &&
        !workspace.historyError &&
        !workspace.error &&
        !workspace.history.length &&
        !run &&
        !workspace.identity?.pending_message && (
          <div className="empty-chat">
            <h1>想去哪里玩？</h1>
            <p className="muted">
              直接告诉我旅行计划，也可以先试试下面的示例。
            </p>
            <div className="chips">
              {mode === "offline"
                ? presets.map((label) => (
                    <button
                      key={label}
                      className="chip"
                      disabled={workspace.busy || noRevision}
                      onClick={() => send(`演示：${label}`, "offline")}
                    >
                      {label}
                    </button>
                  ))
                : examples.map((example) => (
                    <button
                      key={example}
                      className="chip"
                      onClick={() => fill(example)}
                    >
                      {example}
                    </button>
                  ))}
            </div>
            {mode === "offline" && noRevision && (
              <p className="small muted">先在右侧确认旅行条件</p>
            )}
            <p className="small muted">
              实时规划支持日本国内；离线演示使用京都样本。
            </p>
          </div>
        )}
      {workspace.history
        .filter((row) => row.run_id !== run?.run_id)
        .map((row) => (
          <section className="conversation-turn" key={row.run_id}>
            <div className="bubble-user">{row.prompt}</div>
            <div className={`reply reply-${row.status}`}>
              <span className="avatar" aria-hidden="true">
                ◆
              </span>
              <div className="reply-body">
                <p className="run-status">{runStatus(row.status)}</p>
                {row.answer && (
                  <div className="answer">
                    <Markdown text={row.answer} />
                  </div>
                )}
                {row.error_code && !row.answer && (
                  <p className="error">执行未完成：{row.error_code}</p>
                )}
              </div>
            </div>
          </section>
        ))}
      {currentPrompt && <div className="bubble-user">{currentPrompt}</div>}
      {run && (
        <div className={`reply reply-${run.status}`}>
          <span className="avatar" aria-hidden="true">
            ◆
          </span>
          <div className="reply-body">
            <p className="run-status">
              {running ? "处理中…" : runStatus(run.status)}
            </p>
            {running && !run.answer && (
              <p className="step">
                {step ? (
                  `正在${step}…`
                ) : (
                  <span className="shimmer">思考中</span>
                )}
              </p>
            )}
            {run.answer && (
              <div className="answer">
                <Markdown text={run.answer} />
              </div>
            )}
            {run.error_code &&
              (run.error_code === "timeout" || !run.answer) && (
                <p className="error">
                  {run.error_code === "timeout"
                    ? "模型或工具响应超时，本轮执行未完成。已完成的步骤仍保留；超时不代表密钥或额度有误。"
                    : `执行未完成：${run.error_code}。请检查模型配置或调用额度。`}
                </p>
              )}
            <RunSteps events={workspace.events} />
            {workspace.hotels && (
              <HotelResults
                hotels={workspace.hotels}
                disabled={workspace.busy || running}
                revision={workspace.request?.revision}
                hold={workspace.holdOffer}
                choose={(card) =>
                  send(
                    `我选择酒店「${card.hotel_name}」（evidence_id=${card.evidence_id}），请按它重排每天行程，每天结束于酒店。`,
                    mode,
                  )
                }
                compact
              />
            )}
            {workspace.plan?.draft_id && (
              <section className="plan-summary">
                <div>
                  <strong>
                    已生成 {planDays(workspace.plan).length} 天草稿
                  </strong>{" "}
                  ·{" "}
                  {workspace.plan.validation.status === "conflict"
                    ? "有硬冲突，不能确认"
                    : workspace.plan.validation.status === "partial"
                      ? "部分可校验"
                      : "已通过当前范围校验"}
                  <br />
                  <span className="small muted">在右侧查看并确认</span>
                </div>
                <button onClick={openPanel}>查看行程</button>
              </section>
            )}
          </div>
        </div>
      )}
      {workspace.identity?.pending_message && (
        <div className="bubble-user">
          {workspace.identity.pending_message.text}
        </div>
      )}
      {workspace.sendError && (
        <div className="reply reply-failed">
          <p className="error" role="alert">
            {workspace.sendError}
          </p>
        </div>
      )}
    </div>
  );
}

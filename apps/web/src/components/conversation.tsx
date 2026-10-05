/** Chat stream: user messages from this tab, the latest run's reply and the cards it produced. */
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

export type SentMessage = { id: number; text: string };

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
  sent,
  mode,
  send,
  fill,
  openPanel,
}: {
  workspace: Workspace;
  sent: SentMessage[];
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
  return (
    <div className="conversation-stream" aria-live="polite">
      {!sent.length && !run && (
        <div className="empty-chat">
          <h1>想去哪里玩？</h1>
          <p className="muted">直接告诉我旅行计划，也可以先试试下面的示例。</p>
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
      {sent.map((message) => (
        <div className="bubble-user" key={message.id}>
          {message.text}
        </div>
      ))}
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
            {run.error_code && !run.answer && (
              <p className="error">
                执行未完成：{run.error_code}。请检查模型配置或调用额度。
              </p>
            )}
            <RunSteps events={workspace.events} />
            {workspace.hotels && (
              <HotelResults
                hotels={workspace.hotels}
                disabled={workspace.busy}
                revision={workspace.request?.revision}
                hold={workspace.holdOffer}
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

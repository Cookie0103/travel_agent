/** Persisted conversation turns plus the latest run's streamed reply and current cards. */
"use client";
import type { Workspace } from "./workbench";
import { toolLabel } from "./tool-names";
import { HotelResults, planDays } from "./results";
import type { Run } from "@/lib/api";
import {
  belongsToRun,
  matchesRun,
  runCards,
  hotelsForRun,
} from "@/lib/early-cards";
import type { Mode } from "./composer";
import { RunSteps } from "./activity-drawer";
import { Markdown } from "./markdown";
import { Button } from "./ui/button";
import {
  runLabel,
  stageGuidance,
  runErrorMessage,
} from "@/lib/business-status";

const presets = ["比较酒店", "生成行程", "修改第二天下午"];
const examples = [
  "京都三天两夜，2 个大人，预算 5 万日元，想看寺庙，少走路",
  "下雨天京都有哪些室内景点？",
  "帮我比较这几天京都的酒店",
];

function currentStep(workspace: Workspace): string | undefined {
  if (!workspace.run) return undefined;
  const events = workspace.events.filter((event) =>
    belongsToRun(event, workspace.run!),
  );
  const finished = new Set(
    events
      .filter((event) => event.kind === "tool_finished")
      .map((event) => event.tool_call_id),
  );
  const open = events
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
      <Button
        disabled={workspace.busy || workspace.restoring}
        onClick={() => void workspace.login()}
      >
        {workspace.restoring ? "正在恢复上次会话…" : "开始"}
      </Button>
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
  newTrip,
  openPanel,
}: {
  workspace: Workspace;
  mode: Mode;
  send: (text: string, mode: Mode) => void;
  fill: (text: string) => void;
  newTrip: () => void;
  openPanel: () => void;
}) {
  const { run } = workspace;
  const step = currentStep(workspace);
  const running = ["running", "cancelling"].includes(run?.status ?? "");
  const currentPrompt = workspace.history.find(
    (row) => row.run_id === run?.run_id,
  )?.prompt;
  return (
    <div className="conversation-stream" aria-live="polite">
      {workspace.restoring && (
        <div role="status">
          <p className="text-sm text-text-muted">正在恢复对话历史…</p>
          <ReplySkeleton />
        </div>
      )}
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
                      disabled={workspace.busy}
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
            <p className="small muted">
              实时规划支持日本国内；离线演示使用京都样本。
            </p>
          </div>
        )}
      {workspace.history
        .filter((row) => row.run_id !== run?.run_id)
        .map((row) => (
          <section className="conversation-turn" key={row.run_id}>
            <div className="ml-auto w-fit max-w-[85%] rounded-xl bg-primary px-4 py-3 text-base whitespace-pre-wrap text-primary-ink wrap-anywhere">
              {row.prompt}
            </div>
            <div className="bg-bg text-text">
              <div className="min-w-0 space-y-3">
                <p className="run-status">{runLabel(row)}</p>
                {row.answer && !stageGuidance(row) && (
                  <div className="answer">
                    <Markdown text={row.answer} />
                  </div>
                )}
                {runErrorMessage(row) && (
                  <p className="error">{runErrorMessage(row)}</p>
                )}
                <StageFailure
                  workspace={workspace}
                  run={row}
                  latest={false}
                  mode={mode}
                  fill={fill}
                  newTrip={newTrip}
                  openPanel={openPanel}
                />
                <TurnCards
                  workspace={workspace}
                  run={row}
                  latest={false}
                  mode={mode}
                  send={send}
                  openPanel={openPanel}
                />
              </div>
            </div>
          </section>
        ))}
      {currentPrompt && (
        <div className="ml-auto w-fit max-w-[85%] rounded-xl bg-primary px-4 py-3 text-base whitespace-pre-wrap text-primary-ink wrap-anywhere">
          {currentPrompt}
        </div>
      )}
      {run && (
        <div className="bg-bg text-text">
          <div className="min-w-0 space-y-3">
            <p className="run-status">{running ? "处理中…" : runLabel(run)}</p>
            {running && !run.answer && (
              <p className="step">
                {step ? `正在${step}…` : <span>思考中</span>}
              </p>
            )}
            {running && !run.answer && <ReplySkeleton />}
            {run.answer && !stageGuidance(run) && (
              <div className="answer">
                <Markdown text={run.answer} />
              </div>
            )}
            {runErrorMessage(run) && (
              <p className="error">{runErrorMessage(run)}</p>
            )}
            <StageFailure
              workspace={workspace}
              run={run}
              latest
              mode={mode}
              fill={fill}
              newTrip={newTrip}
              openPanel={openPanel}
            />
            <RunSteps
              events={workspace.events.filter((event) =>
                belongsToRun(event, run),
              )}
            />
            {!workspace.events.some((event) => belongsToRun(event, run)) &&
              run.last_sequence > 0 && (
                <button
                  disabled={workspace.busy || workspace.restoring}
                  onClick={() => void workspace.reconnect()}
                >
                  查看执行步骤
                </button>
              )}
            <TurnCards
              workspace={workspace}
              run={run}
              latest
              mode={mode}
              send={send}
              openPanel={openPanel}
            />
          </div>
        </div>
      )}
      {workspace.identity?.pending_message && (
        <div className="ml-auto w-fit max-w-[85%] rounded-xl bg-primary px-4 py-3 text-base whitespace-pre-wrap text-primary-ink wrap-anywhere">
          {workspace.identity.pending_message.text}
        </div>
      )}
      {workspace.sendError && (
        <div className="bg-bg text-text">
          <p className="error" role="alert">
            {workspace.sendError}
          </p>
        </div>
      )}
    </div>
  );
}

function ReplySkeleton() {
  return (
    <div
      aria-hidden="true"
      className="space-y-3 py-3 motion-safe:animate-pulse"
    >
      <div className="h-4 w-3/4 rounded bg-bg-subtle" />
      <div className="h-4 w-full rounded bg-bg-subtle" />
      <div className="h-4 w-1/2 rounded bg-bg-subtle" />
    </div>
  );
}

function StageFailure({
  workspace,
  run,
  latest,
  mode,
  fill,
  newTrip,
  openPanel,
}: {
  workspace: Workspace;
  run: Run;
  latest: boolean;
  mode: Mode;
  fill: (text: string) => void;
  newTrip: () => void;
  openPanel: () => void;
}) {
  const guidance = stageGuidance(run);
  if (!guidance) return null;
  const disabled = workspace.busy || workspace.restoring;
  return (
    <div className="error">
      <p>{guidance.message}</p>
      {latest && guidance.existingPlan && (
        <div className="chips">
          <button
            disabled={disabled}
            onClick={() =>
              void workspace.switchTrip(run.session_id).then((changed) => {
                if (!changed) return;
                openPanel();
                fill(
                  mode === "offline"
                    ? "演示：修改第二天下午"
                    : "请修改现有行程：",
                );
              })
            }
          >
            修改现有行程
          </button>
          <button disabled={disabled} onClick={newTrip}>
            新建另一趟旅行
          </button>
        </div>
      )}
    </div>
  );
}

function TurnCards({
  workspace,
  run,
  latest,
  mode,
  send,
  openPanel,
}: {
  workspace: Workspace;
  run: Run;
  latest: boolean;
  mode: Mode;
  send: (text: string, mode: Mode) => void;
  openPanel: () => void;
}) {
  const references = runCards(run);
  const plan = matchesRun(workspace.planOrigin, run)
    ? workspace.plan
    : undefined;
  const hotels = hotelsForRun(run, workspace.hotels, workspace.hotelOrigin);
  const disabled =
    !latest ||
    workspace.busy ||
    workspace.restoring ||
    ["running", "cancelling"].includes(run.status);
  const view = () => {
    if (plan) openPanel();
    else
      void workspace.viewRunPlan(run.run_id).then((loaded) => {
        if (loaded) openPanel();
      });
  };
  return (
    <>
      {hotels && (
        <HotelResults
          hotels={hotels}
          disabled={disabled}
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
      {(plan || references.draftId || references.planId) && (
        <section className="plan-summary">
          <div>
            {plan?.draft_id ? (
              <>
                <strong>已生成 {planDays(plan).length} 天草稿</strong> ·{" "}
                {plan.validation.status === "conflict"
                  ? "有硬冲突，不能确认"
                  : plan.validation.status === "partial"
                    ? "部分可校验"
                    : "已通过当前范围校验"}
              </>
            ) : (
              <strong>
                {plan?.version
                  ? `已确认行程 · V${plan.version}`
                  : "本轮行程引用"}
              </strong>
            )}
            <br />
            <span className="small muted">
              {latest
                ? "在右侧查看行程"
                : "历史轮次的行程引用，当前状态按需读取"}
            </span>
          </div>
          <button
            disabled={workspace.busy || workspace.restoring}
            onClick={view}
          >
            查看本轮行程
          </button>
        </section>
      )}
    </>
  );
}

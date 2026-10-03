/** Main interaction surface; offline presets and paid SDK execution are visibly separate. */
"use client";
import { useState } from "react";
import { useWorkspace } from "@/lib/use-workspace";
import { Conditions } from "./conditions";
import { HotelResults, PlanResults } from "./results";

export function Workbench() {
  const workspace = useWorkspace();
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"offline" | "live">("offline");
  const [liveConsent, setLiveConsent] = useState(false);
  const active =
    workspace.run && ["running", "cancelling"].includes(workspace.run.status);
  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">TRAVEL AGENT / KYOTO</p>
          <h1>让每一步旅行都有依据</h1>
          <p className="subtitle">
            比较住宿，检查行程，保留修改。你确认后才保存。
          </p>
        </div>
        <div className="header-status">
          <span className="status-dot" />
          本地演示 · 无真实订单
        </div>
      </header>
      <div className="notice">
        景点与攻略来自历史快照，酒店是虚构测试数据，路线是估算。这里展示可验证的规划流程。
      </div>
      {workspace.error && (
        <div className="error-box" role="alert">
          {workspace.error}
          {workspace.identity && (
            <button
              disabled={workspace.busy}
              onClick={() => void workspace.refresh()}
            >
              读取最新条件与行程
            </button>
          )}
          {workspace.run && (
            <button
              disabled={workspace.busy}
              onClick={() => void workspace.reconnect()}
            >
              重新连接进度
            </button>
          )}
        </div>
      )}
      {workspace.identity?.pending_message && (
        <div className="warning">
          上一条消息的响应未知；刷新也保留去重ID。
          <button
            disabled={
              workspace.busy ||
              (workspace.identity.pending_message.mode === "live" &&
                !liveConsent)
            }
            onClick={() => {
              const pending = workspace.identity?.pending_message;
              if (pending) void workspace.send(pending.text, pending.mode);
            }}
          >
            重试未获响应的消息
          </button>
        </div>
      )}
      {!workspace.identity ? (
        <section className="welcome">
          <h2>开始一次京都旅行</h2>
          <p>
            创建本地演示身份后，条件、事件与确认版本会保存在项目数据库。刷新页面可续接当前会话。
          </p>
          <button
            className="primary"
            disabled={workspace.busy}
            onClick={() => void workspace.login()}
          >
            创建演示会话
          </button>
        </section>
      ) : (
        <div className="workspace">
          <aside>
            {workspace.request && (
              <Conditions
                key={workspace.request.revision}
                request={workspace.request}
                disabled={workspace.busy}
                save={workspace.saveConditions}
              />
            )}
            <p className="muted small">
              会话 {workspace.identity.session_id.slice(0, 8)} ·
              令牌仅保留在此标签页，24 小时有效。
            </p>
          </aside>
          <div className="main-column">
            <section className="conversation">
              <div className="section-heading">
                <h2>旅行助手</h2>
                <select
                  aria-label="执行模式"
                  disabled={workspace.busy}
                  value={mode}
                  onChange={(e) => {
                    setMode(e.target.value as typeof mode);
                    setLiveConsent(false);
                  }}
                >
                  <option value="offline">免费离线演示</option>
                  <option value="live">DeepSeek / Claude Agent SDK</option>
                </select>
              </div>
              {mode === "offline" ? (
                <>
                  <p className="muted">
                    下面是固定脚本，使用真实业务工具与数据库；不代表模型自主规划能力。
                  </p>
                  <div className="actions">
                    {["比较酒店", "生成行程", "修改第二天下午"].map((label) => (
                      <button
                        key={label}
                        disabled={
                          workspace.busy || !workspace.request?.revision
                        }
                        onClick={() =>
                          void workspace.send(`演示：${label}`, "offline")
                        }
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <label className="consent">
                  <input
                    type="checkbox"
                    checked={liveConsent}
                    onChange={(e) => setLiveConsent(e.target.checked)}
                  />
                  允许本次消息产生 API
                  费用；服务端还须启用真实模式并通过累计与每日预算。
                </label>
              )}
              <div className="dialogue" aria-live="polite">
                {workspace.run ? (
                  <>
                    <p className="run-status">
                      执行状态：
                      {workspace.busy ? "处理中…" : workspace.run.status}
                    </p>
                    {workspace.run.answer && (
                      <p className="answer">{workspace.run.answer}</p>
                    )}
                  </>
                ) : (
                  <p className="empty">
                    先保存左侧条件，再比较酒店或生成草稿。
                  </p>
                )}
                {workspace.events
                  .filter((event) => event.kind === "tool_finished")
                  .map((event) => (
                    <p className="tool-event" key={event.sequence}>
                      {event.code ? "失败" : "完成"} · {event.tool_name}
                    </p>
                  ))}
              </div>
              <form
                className="composer"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (mode === "offline" || liveConsent)
                    void workspace.send(text, mode);
                }}
              >
                <label className="sr-only" htmlFor="message">
                  消息
                </label>
                <textarea
                  id="message"
                  maxLength={4000}
                  placeholder={
                    mode === "offline"
                      ? "例如：京都室内景点（离线只做固定查询）"
                      : "描述你想查询或修改的内容"
                  }
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <button
                  className="primary"
                  disabled={
                    workspace.busy ||
                    !text.trim() ||
                    (mode === "live" && !liveConsent)
                  }
                >
                  发送
                </button>
              </form>
              {active && (
                <button onClick={() => void workspace.cancel()}>
                  取消当前执行
                </button>
              )}
            </section>
            {workspace.hotels && <HotelResults hotels={workspace.hotels} />}
            {workspace.plan && (
              <PlanResults
                plan={workspace.plan}
                disabled={workspace.busy}
                confirm={workspace.confirm}
                lock={workspace.lock}
              />
            )}
          </div>
        </div>
      )}
      <footer>条件 → 工具事实 → 校验 → 草稿 → 你的确认</footer>
    </main>
  );
}

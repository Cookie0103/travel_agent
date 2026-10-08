/** Chat workspace composed from persisted business state and the selected model. */
"use client";
import { useState } from "react";
import { useWorkspace } from "@/lib/use-workspace";
import { ArticleReference } from "./articles";
import { useModels } from "@/lib/models";
import { Banner } from "./banner";
import { Composer, type Mode } from "./composer";
import { Conversation, Welcome } from "./conversation";
import { TripPanel } from "./trip-panel";

export type Workspace = ReturnType<typeof useWorkspace>;

export function Workbench({ articleId }: { articleId?: string }) {
  const workspace = useWorkspace();
  const [text, setText] = useState("");
  const { mode, setMode, options } = useModels();
  const [collapsed, setCollapsed] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const active = !!(
    workspace.run && ["running", "cancelling"].includes(workspace.run.status)
  );
  const { identity } = workspace;
  const newTrip = () =>
    void workspace.newTrip().then((changed) => {
      if (changed) setText("");
    });
  const submit = (message: string, via: Mode) => {
    if (!message.trim() || workspace.busy || workspace.restoring) return;
    void workspace.send(message, via).then((accepted) => {
      if (accepted) setText((current) => (current === message ? "" : current));
    });
  };
  const attention =
    !!workspace.plan?.draft_id ||
    workspace.bookings.some((booking) => booking.status === "held");
  const panelClass = `trip-panel${collapsed ? " is-collapsed" : ""}${sheetOpen ? " is-sheet-open" : ""}`;
  return (
    <main className="chat-main">
      {!identity ? (
        <>
          {workspace.error && <Banner kind="error">{workspace.error}</Banner>}
          {articleId && (
            <ArticleReference
              articleId={articleId}
              select={(id) => setText(`请参考攻略 ${id}，帮我规划京都旅行。`)}
            />
          )}
          <Welcome workspace={workspace} />
        </>
      ) : (
        <div className="chat-layout">
          <section className="chat-pane">
            <div className="chat-toolbar">
              <label className="trip-picker">
                旅行
                <select
                  aria-label="切换旅行"
                  value={identity.session_id}
                  disabled={workspace.busy || workspace.restoring}
                  onChange={(event) =>
                    void workspace
                      .switchTrip(event.target.value)
                      .then((changed) => {
                        if (changed) setText("");
                      })
                  }
                >
                  {!workspace.trips.some(
                    (trip) => trip.session_id === identity.session_id,
                  ) && <option value={identity.session_id}>当前旅行</option>}
                  {workspace.trips.map((trip) => (
                    <option key={trip.session_id} value={trip.session_id}>
                      {trip.city || "未设置目的地"}
                      {trip.start_date ? ` · ${trip.start_date}` : ""}
                    </option>
                  ))}
                </select>
              </label>
              <button
                disabled={workspace.busy || workspace.restoring}
                onClick={newTrip}
              >
                新建旅行
              </button>
              {workspace.tripCursor && (
                <button
                  disabled={workspace.busy || workspace.restoring}
                  onClick={() => void workspace.loadMoreTrips()}
                >
                  更多旅行
                </button>
              )}

              <button
                className="only-wide"
                aria-expanded={!collapsed}
                onClick={() => setCollapsed((value) => !value)}
              >
                本次行程
                {attention && <span className="dot" aria-label="有待处理" />}
              </button>
              <button
                className="only-narrow"
                aria-expanded={sheetOpen}
                onClick={() => setSheetOpen((value) => !value)}
              >
                本次行程
                {attention && <span className="dot" aria-label="有待处理" />}
              </button>
            </div>
            <div className="chat-scroll">
              {workspace.error && (
                <Banner kind="error">
                  {workspace.error}
                  <button
                    disabled={workspace.busy}
                    onClick={() => void workspace.refresh()}
                  >
                    读取最新条件与行程
                  </button>
                  {workspace.run && (
                    <button
                      disabled={workspace.busy}
                      onClick={() => void workspace.reconnect()}
                    >
                      重新连接进度
                    </button>
                  )}
                </Banner>
              )}
              {identity.pending_message && (
                <Banner kind="warning">
                  上一条消息的响应未知；刷新也保留去重ID。
                  <button
                    disabled={workspace.busy}
                    onClick={() => {
                      const pending = identity.pending_message;
                      if (pending)
                        void workspace.send(pending.text, pending.mode);
                    }}
                  >
                    重试未获响应的消息
                  </button>
                </Banner>
              )}
              <Conversation
                workspace={workspace}
                mode={mode}
                send={submit}
                fill={setText}
                newTrip={newTrip}
                openPanel={() => {
                  setCollapsed(false);
                  setSheetOpen(true);
                }}
              />
            </div>
            <Composer
              mode={mode}
              setMode={setMode}
              options={options}
              text={text}
              setText={setText}
              busy={workspace.busy || workspace.restoring}
              active={active}
              send={submit}
              cancel={() => void workspace.cancel()}
              articleId={articleId}
            />
          </section>
          <TripPanel
            workspace={workspace}
            className={panelClass}
            close={() => {
              setCollapsed(true);
              setSheetOpen(false);
            }}
          />
        </div>
      )}
    </main>
  );
}

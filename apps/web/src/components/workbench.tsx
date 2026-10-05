/** Chat workspace composed from persisted business state and the selected model. */
"use client";
import { useState } from "react";
import { useWorkspace } from "@/lib/use-workspace";
import { ArticleReference } from "./articles";
import { useModels } from "@/lib/models";
import { Banner } from "./banner";
import { Composer, type Mode } from "./composer";
import { Conversation, Welcome, type SentMessage } from "./conversation";
import { DataNotes } from "./data-notes";
import { TripPanel } from "./trip-panel";

export type Workspace = ReturnType<typeof useWorkspace>;

export function Workbench({ articleId }: { articleId?: string }) {
  const workspace = useWorkspace();
  const [text, setText] = useState("");
  const { mode, setMode, options } = useModels();
  const [sent, setSent] = useState<SentMessage[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const active = !!(
    workspace.run && ["running", "cancelling"].includes(workspace.run.status)
  );
  const { identity } = workspace;
  const submit = (message: string, via: Mode) => {
    if (!message.trim() || workspace.busy) return;
    const pending = identity?.pending_message;
    // A mismatched text is rejected by the hook; do not show it as sent.
    if (!pending || (pending.text === message && pending.mode === via))
      setSent((old) => [...old, { id: old.length, text: message }]);
    if (!pending) setText("");
    void workspace.send(message, via);
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
                sent={sent}
                mode={mode}
                send={submit}
                fill={setText}
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
              busy={workspace.busy}
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
          <DataNotes />
        </div>
      )}
    </main>
  );
}

/** Message input with the model selector; live mode is amber and needs per-message billing consent. */
"use client";
import { ArticleReference } from "./articles";

export type Mode = "offline" | "live";

export function Composer({
  mode,
  setMode,
  consent,
  setConsent,
  text,
  setText,
  busy,
  active,
  send,
  cancel,
  articleId,
}: {
  mode: Mode;
  setMode: (mode: Mode) => void;
  consent: boolean;
  setConsent: (value: boolean) => void;
  text: string;
  setText: (value: string) => void;
  busy: boolean;
  active: boolean;
  send: (text: string, mode: Mode) => void;
  cancel: () => void;
  articleId?: string;
}) {
  const blocked = mode === "live" && !consent;
  return (
    <div className="composer-wrap">
      {articleId && (
        <ArticleReference
          articleId={articleId}
          select={(id) => setText(`请参考攻略 ${id}，帮我规划京都旅行。`)}
        />
      )}
      <form
        className={`composer${mode === "live" ? " composer-live" : ""}`}
        onSubmit={(event) => {
          event.preventDefault();
          if (!blocked) send(text, mode);
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
              : "说说你的旅行计划…"
          }
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="composer-bar">
          <label className="model-select">
            <span className="sr-only">执行模式</span>
            <select
              aria-label="执行模式"
              disabled={busy}
              value={mode}
              onChange={(e) => {
                setMode(e.target.value as Mode);
                setConsent(false);
              }}
            >
              <option value="offline">离线演示（免费）</option>
              <option value="live">
                实时模型（DeepSeek / Claude Agent SDK）
              </option>
            </select>
          </label>
          {mode === "live" && (
            <label className="consent">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
              />
              允许本条消息计费
            </label>
          )}
          <span className="composer-hint small muted">
            {mode === "live"
              ? consent
                ? "服务端还须启用真实模式并通过预算。"
                : "需勾选计费许可才能发送。"
              : "固定脚本，使用真实业务工具与数据库。"}
          </span>
          {active ? (
            <button type="button" onClick={cancel}>
              ■ 停止
            </button>
          ) : (
            <button
              className="primary"
              disabled={busy || !text.trim() || blocked}
            >
              发送
            </button>
          )}
        </div>
      </form>
      <div className="disclaimer small muted">
        酒店与订单为模拟数据，不会真实付款 ·{" "}
        <details>
          <summary>数据说明</summary>
          <ul>
            <li>攻略：Wikivoyage 历史快照，营业信息需工具核验。</li>
            <li>酒店：虚构报价，非实时库存。</li>
            <li>路线：估算值。</li>
            <li>当前数据覆盖：京都。</li>
          </ul>
        </details>
      </div>
    </div>
  );
}

/** Message input and keyboard-accessible model choice. */
"use client";
import { useId, useRef, useState } from "react";
import type { ModelOption, Mode } from "@/lib/models";
import { modeLabel } from "@/lib/models";
import { ArticleReference } from "./articles";
export type { Mode } from "@/lib/models";

function ModelSelector({
  mode,
  setMode,
  options,
  disabled,
}: {
  mode: Mode;
  setMode: (mode: Mode) => void;
  options: ModelOption[];
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [focused, setFocused] = useState(0);
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const choose = (index: number) => {
    const option = options[index];
    if (!option?.available) return;
    setMode(option.id);
    setOpen(false);
    trigger.current?.focus();
  };
  return (
    <div
      className="model-picker"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <button
        ref={trigger}
        type="button"
        role="combobox"
        aria-label="选择模型"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={id}
        disabled={disabled}
        onClick={() => {
          setFocused(
            Math.max(
              0,
              options.findIndex((item) => item.id === mode),
            ),
          );
          setOpen(!open);
        }}
        onKeyDown={(event) => {
          if (["ArrowDown", "ArrowUp"].includes(event.key)) {
            event.preventDefault();
            setOpen(true);
            setFocused(
              (index) =>
                (index +
                  (event.key === "ArrowDown" ? 1 : -1) +
                  options.length) %
                options.length,
            );
          } else if (open && ["Enter", " "].includes(event.key)) {
            event.preventDefault();
            choose(focused);
          } else if (event.key === "Escape") setOpen(false);
        }}
        aria-activedescendant={open ? `${id}-${focused}` : undefined}
      >
        {modeLabel(mode)} ▾
      </button>
      {open && (
        <div
          id={id}
          role="listbox"
          aria-label="执行模型"
          className="model-options"
        >
          {options.map((option, index) => (
            <div
              key={option.id}
              id={`${id}-${index}`}
              role="option"
              aria-selected={option.id === mode}
              aria-disabled={!option.available}
              className={`model-option${focused === index ? " is-focused" : ""}${!option.available ? " is-disabled" : ""}`}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(index)}
            >
              <strong>{option.label}</strong>
              <span className="small muted">
                {option.id === "offline"
                  ? "免费 · 模拟数据"
                  : "实时数据 · 按 API 计费"}
              </span>
              {option.reason && (
                <span className="small muted">{option.reason}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Composer({
  mode,
  setMode,
  options,
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
  options: ModelOption[];
  text: string;
  setText: (value: string) => void;
  busy: boolean;
  active: boolean;
  send: (text: string, mode: Mode) => void;
  cancel: () => void;
  articleId?: string;
}) {
  return (
    <div className="composer-wrap">
      {articleId && (
        <ArticleReference
          articleId={articleId}
          select={(id) => setText(`请参考攻略 ${id}，帮我规划京都旅行。`)}
        />
      )}
      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          send(text, mode);
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
          onChange={(event) => setText(event.target.value)}
          onInput={(event) => {
            event.currentTarget.style.height = "auto";
            event.currentTarget.style.height = `${Math.min(event.currentTarget.scrollHeight, 220)}px`;
          }}
        />
        <div className="composer-bar">
          <details className="composer-examples">
            <summary>💡 示例</summary>
            <div>
              {[
                "大阪三天两夜，2成人无儿童1间房，预算6万日元，想看景点并比较酒店",
                "下雨天札幌有哪些室内景点？",
                "帮我修改第二天下午，其他安排保留",
              ].map((example) => (
                <button
                  type="button"
                  key={example}
                  onClick={() => setText(example)}
                >
                  {example}
                </button>
              ))}
            </div>
          </details>
          <ModelSelector
            mode={mode}
            setMode={setMode}
            options={options}
            disabled={busy}
          />
          <span className="composer-hint small muted">
            {mode === "offline"
              ? "固定演示 · 不调用模型"
              : "费用受服务端预算与调用上限限制"}
          </span>
          {active ? (
            <button type="button" onClick={cancel}>
              ■ 停止
            </button>
          ) : (
            <button className="primary" disabled={busy || !text.trim()}>
              发送
            </button>
          )}
        </div>
      </form>
      <div className="disclaimer small muted">
        {mode === "offline"
          ? "离线演示 · 酒店和订单为模拟数据"
          : "行程确认后保存 · 酒店仅查询，不下单"}
      </div>
    </div>
  );
}

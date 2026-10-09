/** Message input and keyboard-accessible model choice. */
"use client";
import type { ModelOption, Mode } from "@/lib/models";
import { shouldSubmitOnEnter } from "@/lib/composer-keys";
import { ArticleReference } from "./articles";
import { DataNotes } from "./data-notes";
import { HoverPopover } from "./ui/hover-popover";
import { Button } from "./ui/button";
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
  return (
    <select
      aria-label="选择模型"
      value={mode}
      disabled={disabled}
      onChange={(event) => {
        const option = options.find(
          (item) => item.id === event.target.value && item.available,
        );
        if (option) setMode(option.id);
      }}
    >
      {options.map((option) => (
        <option key={option.id} value={option.id} disabled={!option.available}>
          {option.label} ·{" "}
          {!option.available && option.reason
            ? option.reason.replace(/^[a-z_]+:\s*/i, "")
            : option.id === "offline"
              ? "免费模拟"
              : "API计费"}
        </option>
      ))}
    </select>
  );
}

const EXAMPLES = [
  "大阪三天两夜，2成人无儿童1间房，预算6万日元，想看景点并比较酒店",
  "下雨天札幌有哪些室内景点？",
  "帮我修改第二天下午，其他安排保留",
];

function Examples({ pick }: { pick: (text: string) => void }) {
  return (
    <HoverPopover label="示例">
      <div className="grid gap-2">
        {EXAMPLES.map((example) => (
          <Button
            type="button"
            variant="ghost"
            className="h-auto justify-start whitespace-normal text-left"
            key={example}
            onClick={() => pick(example)}
          >
            {example}
          </Button>
        ))}
      </div>
    </HoverPopover>
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
      <Examples pick={setText} />
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
          onKeyDown={(event) => {
            if (
              shouldSubmitOnEnter(
                {
                  key: event.key,
                  shiftKey: event.shiftKey,
                  keyCode: event.keyCode,
                  isComposing: event.nativeEvent.isComposing,
                },
                !busy && !active && !!text.trim(),
              )
            ) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          onInput={(event) => {
            event.currentTarget.style.height = "auto";
            event.currentTarget.style.height = `${Math.min(event.currentTarget.scrollHeight, 220)}px`;
          }}
        />
        <div className="composer-bar">
          <ModelSelector
            mode={mode}
            setMode={setMode}
            options={options}
            disabled={busy}
          />
          <span className="composer-hint small muted">
            {mode === "offline" && "固定演示 · 不调用模型"}
          </span>
          {active ? (
            <Button type="button" variant="outline" onClick={cancel}>
              ■ 停止
            </Button>
          ) : (
            <Button type="submit" disabled={busy || !text.trim()}>
              发送
            </Button>
          )}
        </div>
      </form>
      <DataNotes />
      <div className="disclaimer small muted">
        {mode === "offline"
          ? "离线演示 · 酒店和订单为模拟数据"
          : "行程确认后保存 · 酒店仅查询，不下单"}
      </div>
    </div>
  );
}

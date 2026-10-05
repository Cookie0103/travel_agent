/** Data attribution kept reachable but out of the chat: hover, click or focus opens it. */
"use client";
import { usePopover } from "./use-popover";

export function DataNotes() {
  const { open, toggle, rootProps } = usePopover();
  return (
    <div className="data-notes" {...rootProps}>
      {open && (
        <div role="dialog" aria-label="数据说明" className="data-notes-pop">
          <p>
            实时景点和路线：Google
            Maps。酒店：乐天实时查询，报价以供应商页面为准。
          </p>
          <p>
            天气数据：
            <a
              href="https://open-meteo.com/"
              target="_blank"
              rel="noopener noreferrer"
            >
              Open-Meteo.com（CC BY 4.0）
            </a>
          </p>
        </div>
      )}
      <button
        type="button"
        aria-expanded={open}
        aria-label="数据说明"
        onClick={toggle}
      >
        ⓘ 数据说明
      </button>
    </div>
  );
}

/** Shared hover / click / focus / Escape behaviour for small popovers. */
"use client";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
} from "react";

export const POPOVER_CLOSE_DELAY_MS = 350;

export function usePopover() {
  const [pinned, setPinned] = useState(false);
  const [hover, setHover] = useState(false);
  const rootRef = useRef<HTMLElement | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelClose = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  }, []);
  const closeNow = useCallback(() => {
    cancelClose();
    setPinned(false);
    setHover(false);
  }, [cancelClose]);
  const enter = useCallback(() => {
    cancelClose();
    setHover(true);
  }, [cancelClose]);

  useEffect(() => cancelClose, [cancelClose]);

  // Outside pointerdown closes; a drag-selection ending outside does not.
  useEffect(() => {
    if (!pinned && !hover) return;
    const onDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) closeNow();
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [pinned, hover, closeNow]);

  return {
    open: pinned || hover,
    toggle: () => setPinned((value) => !value),
    rootProps: {
      ref: (node: HTMLElement | null) => {
        rootRef.current = node;
      },
      onMouseEnter: enter,
      onMouseLeave: () => {
        cancelClose();
        timer.current = setTimeout(
          () => setHover(false),
          POPOVER_CLOSE_DELAY_MS,
        );
      },
      onFocus: enter,
      onBlur: (event: FocusEvent<HTMLElement>) => {
        // null relatedTarget = click on non-focusable text; pointerdown handles outside clicks.
        const next = event.relatedTarget;
        if (next && !event.currentTarget.contains(next as Node)) closeNow();
      },
      onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
        if (event.key === "Escape") closeNow();
      },
    },
  };
}

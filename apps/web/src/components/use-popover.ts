/** Shared hover / click / focus / Escape behaviour for small popovers. */
"use client";
import { useState, type FocusEvent, type KeyboardEvent } from "react";

export function usePopover() {
  const [pinned, setPinned] = useState(false);
  const [hover, setHover] = useState(false);
  return {
    open: pinned || hover,
    toggle: () => setPinned((value) => !value),
    rootProps: {
      onMouseEnter: () => setHover(true),
      onMouseLeave: () => setHover(false),
      onFocus: () => setHover(true),
      onBlur: (event: FocusEvent<HTMLElement>) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setPinned(false);
          setHover(false);
        }
      },
      onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
        if (event.key === "Escape") {
          setPinned(false);
          setHover(false);
        }
      },
    },
  };
}

/** Hover preview and click pinning; Radix handles dismissal and portal focus. */
"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "./button";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

export function HoverPopover({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const pinned = useRef(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancel = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const enter = () => {
    cancel();
    setOpen(true);
  };
  const leave = () => {
    cancel();
    if (!pinned.current) timer.current = setTimeout(() => setOpen(false), 350);
  };
  const close = () => {
    cancel();
    pinned.current = false;
    setOpen(false);
  };
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
        else enter();
      }}
    >
      <PopoverTrigger asChild>
        <Button
          ref={trigger}
          type="button"
          variant="ghost"
          size="sm"
          onMouseEnter={enter}
          onMouseLeave={leave}
          onFocus={enter}
          onClick={(event) => {
            event.preventDefault();
            pinned.current = !pinned.current;
            if (pinned.current) {
              enter();
              content.current
                ?.querySelector<HTMLElement>("button, a[href]")
                ?.focus();
            } else close();
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              pinned.current = true;
              enter();
              content.current
                ?.querySelector<HTMLElement>("button, a[href]")
                ?.focus();
            }
          }}
        >
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        ref={content}
        aria-label={label}
        side="top"
        onMouseEnter={enter}
        onMouseLeave={leave}
        onOpenAutoFocus={(event) => {
          if (!pinned.current) event.preventDefault();
        }}
        onCloseAutoFocus={(event) => event.preventDefault()}
        onEscapeKeyDown={() => trigger.current?.focus()}
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}

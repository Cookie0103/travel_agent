/** shadcn/ui Popover composition; Radix owns focus, Escape and outside dismissal. */
"use client";
import * as React from "react";
import * as Primitive from "@radix-ui/react-popover";
import { cn } from "@/lib/utils";

export const Popover = Primitive.Root;
export const PopoverTrigger = Primitive.Trigger;

export function PopoverContent({
  className,
  align = "start",
  sideOffset = 8,
  ...props
}: React.ComponentProps<typeof Primitive.Content>) {
  return (
    <Primitive.Portal>
      <Primitive.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(
          "z-50 w-80 max-w-[calc(100vw-32px)] rounded-xl border border-border bg-bg p-4 text-base text-text outline-none",
          className,
        )}
        {...props}
      />
    </Primitive.Portal>
  );
}

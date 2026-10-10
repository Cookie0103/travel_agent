/** shadcn/ui Button pattern, adapted to design/07; public MIT upstream: shadcn-ui/ui. */
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const variants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border px-4 py-2 text-base font-medium leading-6 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "border-primary bg-primary text-primary-ink hover:bg-primary/80",
        outline: "border-border bg-bg text-text hover:bg-bg-subtle",
        ghost:
          "border-transparent bg-transparent text-text-muted hover:bg-bg-subtle hover:text-text",
      },
      size: {
        default: "min-h-10",
        sm: "min-h-8 px-3 py-1 text-sm",
        icon: "size-10 p-0",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof variants> & { asChild?: boolean }) {
  const Component = asChild ? Slot : "button";
  return (
    <Component
      data-slot="button"
      className={cn(variants({ variant, size }), className)}
      {...props}
    />
  );
}

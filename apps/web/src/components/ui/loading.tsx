import type { ReactNode } from "react";

export function Skeleton() {
  return (
    <div
      aria-hidden="true"
      className="space-y-3 py-3 motion-safe:animate-pulse"
    >
      <div className="h-4 w-3/4 rounded bg-bg-subtle" />
      <div className="h-4 w-full rounded bg-bg-subtle" />
      <div className="h-4 w-1/2 rounded bg-bg-subtle" />
    </div>
  );
}
export function Loading({ children }: { children: ReactNode }) {
  return (
    <div role="status">
      <p className="text-sm text-text-muted">{children}</p>
      <Skeleton />
    </div>
  );
}

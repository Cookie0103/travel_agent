/** Keyboard selection only; switching views never reloads the active conversation. */
export type WorkspaceTab = "chat" | "trip";
export function workspaceTab(
  key: string,
  current: WorkspaceTab,
): WorkspaceTab | undefined {
  if (key === "Home") return "chat";
  if (key === "End") return "trip";
  if (key === "ArrowLeft" || key === "ArrowRight")
    return current === "chat" ? "trip" : "chat";
}

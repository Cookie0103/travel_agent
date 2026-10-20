/** Enter sends, Shift+Enter breaks the line; never while an IME is composing. */
export function shouldSubmitOnEnter(
  event: {
    key: string;
    shiftKey: boolean;
    isComposing: boolean;
    keyCode: number;
  },
  canSend: boolean,
): boolean {
  return (
    event.key === "Enter" &&
    !event.shiftKey &&
    !event.isComposing &&
    event.keyCode !== 229 &&
    canSend
  );
}

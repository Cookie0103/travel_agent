/** Sticky-bottom helper: new content only follows the reader who is already near the end. */
export function isNearBottom(
  box: { scrollTop: number; clientHeight: number; scrollHeight: number },
  threshold = 100,
): boolean {
  return box.scrollHeight - box.scrollTop - box.clientHeight <= threshold;
}

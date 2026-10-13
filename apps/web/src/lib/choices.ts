/** Server options supply the only choice values; session/revision checks also run on submission. */
import type { Choice, MessageSelection } from "./api";

export function choiceDisabled(
  card: Choice,
  busy: boolean,
  sessionId?: string,
  revision?: number,
  now = Date.now(),
): boolean {
  return (
    busy ||
    !card.choice_id ||
    card.session_id !== sessionId ||
    card.expected_revision !== revision ||
    !!card.answered_option_id ||
    card.stale ||
    !!(card.expires_at && (now === 0 || Date.parse(card.expires_at) <= now))
  );
}

export function choiceMessage(
  card: Choice,
  optionId: string,
): MessageSelection {
  if (!card.choice_id) throw new Error("选择卡缺少编号");
  if (!card.options.some((o) => o.option_id === optionId))
    throw new Error("选项不属于此选择卡");
  return {
    expected_revision: card.expected_revision,
    selection: { choice_id: card.choice_id, option_id: optionId },
  };
}

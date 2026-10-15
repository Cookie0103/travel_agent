/** Server options supply the only choice values; session/revision checks also run on submission. */
import type { Choice, MessageSelection } from "./api";
import type { components } from "./api-types";

export type DetailsAnswer = components["schemas"]["TravelDetailsAnswer"];

export function validDetailsAnswer(value: unknown): value is DetailsAnswer {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const data = value as Record<string, unknown>;
  if (
    Object.keys(data).some(
      (key) =>
        !["transport", "pace", "times_correct", "corrected_times"].includes(
          key,
        ),
    ) ||
    !["walk", "transit", "taxi"].includes(String(data.transport)) ||
    !["标准", "慢节奏", "特种兵"].includes(String(data.pace)) ||
    (data.times_correct != null && typeof data.times_correct !== "boolean")
  )
    return false;
  if (data.times_correct !== false) return data.corrected_times == null;
  return (
    Array.isArray(data.corrected_times) &&
    data.corrected_times.length > 0 &&
    data.corrected_times.length <= 20 &&
    data.corrected_times.every(
      (text) => typeof text === "string" && !!text.trim() && text.length <= 200,
    )
  );
}

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
  details?: DetailsAnswer,
): Extract<MessageSelection, { selection: unknown }> {
  if (!card.choice_id) throw new Error("选择卡缺少编号");
  if (!card.options.some((o) => o.option_id === optionId))
    throw new Error("选项不属于此选择卡");
  if (card.kind === "travel_details") {
    if (
      !validDetailsAnswer(details) ||
      !card.details ||
      !card.details.transport_options.some(
        (o) => o.value === details.transport,
      ) ||
      !card.details.pace_options.some((o) => o.value === details.pace) ||
      !!card.details.time_constraints.length !==
        (typeof details.times_correct === "boolean") ||
      (details.times_correct === false
        ? !details.corrected_times ||
          details.corrected_times.length !==
            card.details.time_constraints.length ||
          details.corrected_times.some(
            (text) => !text.trim() || text.length > 200,
          )
        : details.corrected_times != null)
    )
      throw new Error("请选好交通、旅行节奏，并确认或更正时间。");
  } else if (details) throw new Error("普通选择不能混填旅行条件");
  return {
    expected_revision: card.expected_revision,
    selection: {
      choice_id: card.choice_id,
      option_id: optionId,
      ...(details ? { details } : {}),
    },
  };
}

export function detailsSummary(card: Choice, details: DetailsAnswer): string {
  const shown = card.details;
  if (!shown) throw new Error("缺少出行安排");
  const transport = shown.transport_options.find(
    (o) => o.value === details.transport,
  )?.label;
  const pace = shown.pace_options.find((o) => o.value === details.pace)?.label;
  const times =
    details.times_correct === false
      ? details.corrected_times?.join("；")
      : shown.time_constraints.join("；");
  return `确认出行安排：交通：${transport}；旅行节奏：${pace}${times ? `；抵达/离开安排：${times}` : ""}。`;
}

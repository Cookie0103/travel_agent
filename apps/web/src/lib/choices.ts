/** Server options supply the only choice values; session/revision checks also run on submission. */
import type { Choice, MessageSelection } from "./api";
import type { components } from "./api-types";

export type FormGroup = components["schemas"]["FormGroup"];
export type FormAnswers = Record<string, string[]>;
export type FormSelection = components["schemas"]["ChoiceSelection"];

/** The server converts legacy travel_details rows to form cards, so there is one shape. */
export function formOf(card: Choice): FormGroup[] | null {
  return card.form?.groups ?? null;
}

export const isAnswerMap = (value: unknown): value is FormAnswers =>
  typeof value === "object" &&
  value !== null &&
  !Array.isArray(value) &&
  Object.values(value).every(
    (v) => Array.isArray(v) && v.every((s) => typeof s === "string"),
  );

/** Checks answers only against the card's own groups; no hard-coded enums. */
export function validAnswers(card: Choice, answers: FormAnswers): boolean {
  const groups = formOf(card);
  if (!groups) return false;
  const keys = new Set(
    groups.flatMap((g) =>
      g.kind === "times" ? [g.key, `${g.key}_corrected`] : [g.key],
    ),
  );
  if (Object.keys(answers).some((key) => !keys.has(key))) return false;
  return groups.every((g) => {
    const given = answers[g.key] ?? [];
    if (g.required && !given.length) return false;
    if (g.kind === "choice")
      return (
        new Set(given).size === given.length &&
        (g.multi || given.length <= 1) &&
        given.every((id) => g.options.some((o) => o.option_id === id))
      );
    const fixed = answers[`${g.key}_corrected`];
    if (given.length > 1 || (given.length && !["yes", "no"].includes(given[0])))
      return false;
    if (given[0] !== "no") return fixed === undefined;
    return (
      fixed?.length === g.shown?.length &&
      fixed.every((t) => !!t.trim() && t.length <= 200)
    );
  });
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
  answers?: FormAnswers,
): Extract<MessageSelection, { selection: unknown }> {
  if (!card.choice_id) throw new Error("选择卡缺少编号");
  if (!card.options.some((o) => o.option_id === optionId))
    throw new Error("选项不属于此选择卡");
  if (formOf(card)) {
    if (!answers || !validAnswers(card, answers))
      throw new Error("请完成所有必填项，并确认或更正时间。");
  } else if (answers) throw new Error("普通选择不能混填表单答案");
  const selection: FormSelection = {
    choice_id: card.choice_id,
    option_id: optionId,
    ...(answers ? { answers } : {}),
  };
  return { expected_revision: card.expected_revision, selection };
}

/** Chat text for a submitted form: each group's chosen labels, or the corrected times. */
export function answersSummary(card: Choice, answers: FormAnswers): string {
  const parts = (formOf(card) ?? []).map((g) => {
    if (g.kind === "times")
      return `${g.label.replace(/[？?]$/, "")}：${
        answers[g.key]?.[0] === "no"
          ? answers[`${g.key}_corrected`]?.join("；")
          : g.shown?.join("；")
      }`;
    const labels = (answers[g.key] ?? []).map(
      (id) => g.options.find((o) => o.option_id === id)?.label,
    );
    return `${g.label}：${labels.join("、")}`;
  });
  return `确认：${parts.join("；")}。`;
}

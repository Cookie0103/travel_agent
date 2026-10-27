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

export const TEXT_MAX = 40;
export const textKey = (key: string) => `${key}_text`;
const textGroup = (g: FormGroup) => g.kind === "choice" && !!g.allow_text;
const isTripAsk = (card: Choice) => card.form?.purpose === "trip_ask";

/** Option OR free text per group: choosing one clears the other. */
export function setGroupOption(
  answers: FormAnswers,
  group: FormGroup,
  optionId: string,
): FormAnswers {
  const next = { ...answers };
  delete next[textKey(group.key)];
  const value = next[group.key] ?? [];
  const toggled = value.includes(optionId)
    ? value.filter((v) => v !== optionId)
    : group.multi
      ? [...value, optionId]
      : [optionId];
  if (toggled.length) next[group.key] = toggled;
  else delete next[group.key];
  return next;
}

export function setGroupText(
  answers: FormAnswers,
  group: FormGroup,
  text: string,
): FormAnswers {
  if (!textGroup(group)) return answers;
  const next = { ...answers };
  delete next[group.key];
  if (text) next[textKey(group.key)] = [text];
  else delete next[textKey(group.key)];
  return next;
}

/** Checks answers only against the card's own groups; no hard-coded enums. */
export function validAnswers(card: Choice, answers: FormAnswers): boolean {
  const groups = formOf(card);
  if (!groups) return false;
  const keys = new Set(
    groups.flatMap((g) =>
      g.kind === "times"
        ? [g.key, `${g.key}_corrected`]
        : textGroup(g)
          ? [g.key, textKey(g.key)]
          : [g.key],
    ),
  );
  if (Object.keys(answers).some((key) => !keys.has(key))) return false;
  // The combined ask card confirms with zero answers (all "not sure"); other forms need one.
  if (
    !isTripAsk(card) &&
    !groups.some((g) => answers[g.key]?.length || answers[textKey(g.key)])
  )
    return false;
  return groups.every((g) => {
    const given = answers[g.key] ?? [];
    const fixed = answers[`${g.key}_corrected`];
    const typed = answers[textKey(g.key)];
    if (typed !== undefined)
      return (
        textGroup(g) &&
        !given.length &&
        typed.length === 1 &&
        !!typed[0].trim() &&
        typed[0].length <= TEXT_MAX
      );
    if (!given.length) return !g.required && fixed === undefined;
    if (g.kind === "choice")
      return (
        new Set(given).size === given.length &&
        (g.multi || given.length <= 1) &&
        given.every((id) => g.options.some((o) => o.option_id === id))
      );
    if (given.length > 1 || !["yes", "no"].includes(given[0])) return false;
    if (given[0] !== "no") return fixed === undefined;
    return !!fixed?.length && fixed.every((t) => !!t.trim() && t.length <= 200);
  });
}

/** Submit-time cleanup: "not correct" with no text typed counts as the time question unanswered. */
export function cleanAnswers(answers: FormAnswers): FormAnswers {
  const next = { ...answers };
  for (const [key, value] of Object.entries(next))
    if (key.endsWith("_text")) {
      const text = value[0]?.trim();
      if (text) next[key] = [text];
      else delete next[key];
    }
  if (next.times?.[0] === "no" && !next.times_corrected?.[0]?.trim()) {
    delete next.times;
    delete next.times_corrected;
  }
  return next;
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

export type Pick = { card: Choice; optionId: string };

export function choiceMessage(
  card: Choice,
  optionId: string,
  answers?: FormAnswers,
  also: Pick[] = [],
): Extract<MessageSelection, { selection: unknown }> {
  if (!card.choice_id) throw new Error("选择卡缺少编号");
  if (!card.options.some((o) => o.option_id === optionId))
    throw new Error("选项不属于此选择卡");
  if (
    also.some(
      (p) =>
        !p.card.choice_id ||
        p.card.kind !== "memory_confirm" ||
        !p.card.options.some((o) => o.option_id === p.optionId),
    ) ||
    (also.length && card.kind !== "memory_confirm")
  )
    throw new Error("只能把同一轮的记忆确认卡一起提交");
  if (formOf(card)) {
    if (!answers || !validAnswers(card, answers))
      throw new Error("请完成所有必填项，并确认或更正时间。");
  } else if (card.kind === "hotel_assign") {
    // deny must name the city; confirm/dismiss never carry answers.
    const city = answers?.city;
    if (optionId === "deny") {
      if (
        Object.keys(answers ?? {}).some((key) => key !== "city") ||
        city?.length !== 1 ||
        !city[0].trim() ||
        city[0].length > TEXT_MAX
      )
        throw new Error("请填写应归入的城市（不超过40字）。");
    } else if (answers) throw new Error("此选项不能附带答案");
  } else if (answers) throw new Error("普通选择不能混填表单答案");
  // `also` is optional on input; the generated type reflects the output shape.
  const selection = {
    choice_id: card.choice_id,
    option_id: optionId,
    ...(answers ? { answers } : {}),
    ...(also.length
      ? {
          also: also.map((p) => ({
            choice_id: p.card.choice_id!,
            option_id: p.optionId,
          })),
        }
      : {}),
  } as FormSelection;
  return { expected_revision: card.expected_revision, selection };
}

export const assignOf = (card: Choice) => card.assign ?? null;

/** Chat text for a submitted form: each group's chosen labels, typed text or corrected times. */
export function answersSummary(card: Choice, answers: FormAnswers): string {
  // Groups the user left unanswered are omitted: never echo an empty "交通方式：".
  const parts = (formOf(card) ?? []).flatMap((g) => {
    if (g.kind === "times") {
      const value =
        answers[g.key]?.[0] === "no"
          ? answers[`${g.key}_corrected`]?.join("；")
          : answers[g.key]?.length
            ? g.shown?.join("；")
            : "";
      return value ? [`${g.label.replace(/[？?]$/, "")}：${value}`] : [];
    }
    const labels = [
      ...(answers[g.key] ?? []).flatMap((id) => {
        const label = g.options.find((o) => o.option_id === id)?.label;
        return label ? [label] : [];
      }),
      ...(answers[textKey(g.key)] ?? []),
    ];
    return labels.length ? [`${g.label}：${labels.join("、")}`] : [];
  });
  return parts.length ? `确认：${parts.join("；")}。` : "确认出行信息";
}

/** The visible chat message for any card submission. */
export function selectionText(
  card: Choice,
  optionId: string,
  answers?: FormAnswers,
): string {
  if (answers && formOf(card)) return answersSummary(card, answers);
  const label = card.options.find((o) => o.option_id === optionId)?.label;
  const city = answers?.city?.[0]?.trim();
  if (card.kind === "hotel_assign" && optionId === "deny" && city)
    return `用户选择：${label}，应归到${city}的住宿段`;
  return `用户选择：${label}`;
}

/** Memory cards' effective picks: the server's default option, overridden by the user's own clicks. */
export function memoryPicks(
  cards: Choice[],
  picked: Record<string, string>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const card of cards) {
    const id = card.choice_id;
    if (!id || card.answered_option_id) continue;
    const fallback = card.default_option_id;
    const base =
      fallback && card.options.some((o) => o.option_id === fallback)
        ? fallback
        : undefined;
    const value = picked[id] ?? base;
    if (value) out[id] = value;
  }
  return out;
}

import type { MemoryFact } from "./memory.ts";
/** Pace lives in soft_constraints under a stable prefix so the model and server see it as plain text. */
const PACE_PREFIX = "节奏：";
export const PACES = ["标准", "特种兵", "慢节奏"] as const;
export type Pace = (typeof PACES)[number];

const aliases: Record<string, Pace> = {
  标准: "标准",
  标准节奏: "标准",
  正常: "标准",
  慢节奏: "慢节奏",
  轻松: "慢节奏",
  佛系: "慢节奏",
  悠闲: "慢节奏",
  特种兵: "特种兵",
};

export function currentPace(
  softConstraints: readonly string[],
  hardConstraints: readonly string[] = [],
): Pace | "" {
  for (const item of [...hardConstraints, ...softConstraints]) {
    const key = item.replace(/^节奏：/, "").trim();
    const pace = Object.hasOwn(aliases, key) ? aliases[key] : undefined;
    if (pace) return pace;
  }
  return "";
}

/** Replace any existing pace entry and keep every other constraint in order. */
export function mergePace(
  softConstraints: readonly string[],
  pace: Pace | "",
): string[] {
  const existing = softConstraints.filter(
    (item) => item.startsWith(PACE_PREFIX) || !!currentPace([item]),
  );
  if (pace && existing.length === 1 && existing[0] === `${PACE_PREFIX}${pace}`)
    return [...softConstraints];
  return [
    ...softConstraints.filter(
      (item) => !item.startsWith(PACE_PREFIX) && !currentPace([item]),
    ),
    ...(pace ? [`${PACE_PREFIX}${pace}`] : []),
  ];
}

/** Display only: an unset pace is shown as the assumed 标准, never written to the request. */
export function paceLabel(pace: Pace | ""): string {
  return pace ? `节奏：${pace}` : "节奏：标准（默认假设，未指定）";
}

/** The pace line states its source: this request, a confirmed long-term preference, or the assumption. */
export function paceLine(pace: Pace | "", longTerm: Pace | ""): string {
  if (pace) return `节奏：${pace}（本次指定）`;
  if (longTerm) return `节奏：${longTerm}（长期偏好）`;
  return paceLabel("");
}

/** Newest active long-term pace fact from the memory API rows the panel already reads. */
export function longTermPace(
  facts: readonly Pick<
    MemoryFact,
    "key" | "value" | "scope" | "status" | "created_at"
  >[],
): Pace | "" {
  const current = facts
    .filter(
      (fact) =>
        fact.key === "pace" &&
        fact.scope === "long_term" &&
        fact.status === "active" &&
        !!fact.value &&
        !!currentPace([`${PACE_PREFIX}${fact.value}`]),
    )
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
  return current ? currentPace([`${PACE_PREFIX}${current.value}`]) : "";
}

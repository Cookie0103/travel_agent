/** Pace lives in soft_constraints under a stable prefix so the model and server see it as plain text. */
export const PACE_PREFIX = "节奏：";
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

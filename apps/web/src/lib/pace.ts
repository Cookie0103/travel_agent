/** Pace lives in soft_constraints under a stable prefix so the model and server see it as plain text. */
export const PACE_PREFIX = "节奏：";
export const PACES = ["标准", "特种兵", "慢节奏"] as const;
export type Pace = (typeof PACES)[number];

export function currentPace(softConstraints: readonly string[]): Pace {
  const found = softConstraints.find((item) => item.startsWith(PACE_PREFIX));
  const pace = found?.slice(PACE_PREFIX.length);
  return PACES.find((option) => option === pace) ?? "标准";
}

/** Replace any existing pace entry and keep every other constraint in order. */
export function mergePace(
  softConstraints: readonly string[],
  pace: Pace,
): string[] {
  return [
    ...softConstraints.filter((item) => !item.startsWith(PACE_PREFIX)),
    `${PACE_PREFIX}${pace}`,
  ];
}

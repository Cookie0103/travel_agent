/** Diff the visible form against canonical conditions; absent facts stay unknown. */
import type { RequestState } from "./api";
import type { components } from "./api-types";
import { currentPace, mergePace, PACES, type Pace } from "./pace.ts";

export type ConditionsForm = Record<
  | "city"
  | "start_date"
  | "end_date"
  | "adults"
  | "child_ages"
  | "child_state"
  | "rooms"
  | "budget"
  | "transport"
  | "departure_time"
  | "pace",
  string
>;
export type ConditionPatch = {
  set: Partial<components["schemas"]["TravelConditions"]>;
  clear: NonNullable<components["schemas"]["RequestPatch"]["clear"]>;
};

export function conditionsForm(request: RequestState): ConditionsForm {
  const text = (value: unknown) =>
    value === null || value === undefined ? "" : String(value);
  return {
    city: text(request.city),
    start_date: text(request.start_date),
    end_date: text(request.end_date),
    adults: text(request.adults),
    child_ages: request.child_ages?.join(",") ?? "",
    child_state:
      request.child_ages == null
        ? "unknown"
        : request.child_ages.length
          ? "ages"
          : "none",
    rooms: text(request.rooms),
    budget: text(request.budget),
    transport: text(request.transport),
    departure_time: text(request.departure_time),
    pace: currentPace(request.soft_constraints ?? []),
  };
}

export function conditionPatch(
  request: RequestState,
  form: ConditionsForm,
): ConditionPatch {
  const original = conditionsForm(request);
  const set: NonNullable<ConditionPatch["set"]> = {};
  const clear: string[] = [];
  for (const key of [
    "city",
    "start_date",
    "end_date",
    "adults",
    "rooms",
    "budget",
    "transport",
    "departure_time",
  ] as const) {
    const value = form[key].trim();
    const before = original[key].trim();
    const time = (text: string) => (text.length === 5 ? `${text}:00` : text);
    const equivalent =
      value === before ||
      ((key === "budget" || key === "adults" || key === "rooms") &&
        value !== "" &&
        before !== "" &&
        Number.isFinite(Number(value)) &&
        Number(value) === Number(before)) ||
      (key === "departure_time" && time(value) === time(before));
    if (equivalent) continue;
    if (!value) {
      if (before) clear.push(key);
      continue;
    }
    if (key === "adults" || key === "rooms") {
      const number = Number(value);
      if (
        !Number.isInteger(number) ||
        number < 1 ||
        number > (key === "adults" ? 12 : 6)
      )
        throw new Error(
          key === "adults" ? "成人数请填1–12的整数。" : "房间数请填1–6的整数。",
        );
      set[key] = number;
    } else if (key === "transport") {
      if (!["walk", "transit", "taxi"].includes(value))
        throw new Error("请选择有效交通方式。");
      set.transport = value as NonNullable<RequestState["transport"]>;
    } else set[key] = value;
  }
  if (form.child_state === "unknown") {
    if (request.child_ages != null) clear.push("child_ages");
  } else if (form.child_state === "none") {
    if (request.child_ages == null || request.child_ages.length)
      set.child_ages = [];
  } else if (form.child_state === "ages") {
    const tokens = form.child_ages.split(/[,，]/).map((value) => value.trim());
    const ages = tokens.map(Number);
    if (
      tokens.some((value) => !value) ||
      ages.length > 8 ||
      ages.some((age) => !Number.isInteger(age) || age < 0 || age > 17)
    )
      throw new Error(
        "儿童年龄请填0–17的整数，用逗号分开，最多8名；婴儿可填0。",
      );
    if (JSON.stringify(ages) !== JSON.stringify(request.child_ages))
      set.child_ages = ages;
  } else throw new Error("请选择有效儿童情况。");
  if (form.pace !== original.pace) {
    if (form.pace && !PACES.includes(form.pace as Pace))
      throw new Error("请选择有效节奏。");
    set.soft_constraints = mergePace(
      request.soft_constraints ?? [],
      form.pace as Pace | "",
    );
  }
  return { set, clear };
}

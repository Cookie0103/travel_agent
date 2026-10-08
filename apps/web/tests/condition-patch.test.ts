/** The visible form must not invent conditions or submit semantic no-ops. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { conditionsForm, conditionPatch } from "../src/lib/condition-patch.ts";
import type { RequestState } from "../src/lib/api";
const request = {
  revision: 7,
  city: "京都",
  start_date: "2026-11-03",
  end_date: "2026-11-05",
  adults: 2,
  child_ages: null,
  rooms: 1,
  budget: "50000.00",
  currency: "JPY",
  transport: "walk",
  departure_time: "09:00:00",
  soft_constraints: ["少走路"],
} as unknown as RequestState;

test("saving untouched visible fields preserves revision semantics and unknown children/pace", () => {
  const form = conditionsForm(request);
  assert.equal(form.pace, "");
  assert.equal(form.child_ages, "");
  assert.deepEqual(conditionPatch(request, form), { set: {}, clear: [] });
  assert.equal(request.revision, 7);
  assert.equal(request.child_ages, null);
});

test("empty conditions have no hidden city, dates, party, budget or transport defaults", () => {
  const empty = {
    revision: 0,
    soft_constraints: [],
  } as unknown as RequestState;
  const form = conditionsForm(empty);
  assert.equal(form.child_state, "unknown");
  assert.ok(
    Object.entries(form)
      .filter(([key]) => key !== "child_state")
      .every(([, value]) => value === ""),
  );
  assert.deepEqual(conditionPatch(empty, form), { set: {}, clear: [] });
});

test("equivalent normalized city, Decimal budget and zero-second time are not changes", () => {
  const form = conditionsForm(request);
  assert.deepEqual(
    conditionPatch(request, {
      ...form,
      city: " 京都 ",
      budget: "50000",
      departure_time: "09:00",
    }),
    { set: {}, clear: [] },
  );
});

test("an explicit edit submits only that field while blank existing values use clear", () => {
  const form = conditionsForm(request);
  assert.deepEqual(conditionPatch(request, { ...form, budget: "70000" }), {
    set: { budget: "70000" },
    clear: [],
  });
  assert.deepEqual(
    conditionPatch(request, { ...form, budget: "", transport: "" }),
    { set: {}, clear: ["budget", "transport"] },
  );
});

test("pace editing retains unrelated constraints, and no-op preserves their order", () => {
  const paced = { ...request, soft_constraints: ["节奏：慢节奏", "少走路"] };
  const form = conditionsForm(paced);
  assert.deepEqual(conditionPatch(paced, form), { set: {}, clear: [] });
  assert.deepEqual(conditionPatch(paced, { ...form, pace: "" }), {
    set: { soft_constraints: ["少走路"] },
    clear: [],
  });
  assert.deepEqual(
    conditionPatch(request, { ...conditionsForm(request), pace: "标准" }),
    { set: { soft_constraints: ["少走路", "节奏：标准"] }, clear: [] },
  );
});

test("infant zero is retained and incomplete or invalid age tokens cannot invent zero", () => {
  const infant = { ...request, child_ages: [0] };
  assert.deepEqual(conditionPatch(infant, conditionsForm(infant)), {
    set: {},
    clear: [],
  });
  for (const child_ages of ["5,", ",5", "-1", "18", "1.5"]) {
    assert.throws(
      () =>
        conditionPatch(request, {
          ...conditionsForm(request),
          child_state: "ages",
          child_ages,
        }),
      /儿童年龄/,
    );
  }
});

test("equivalent integer counts are a no-op and cannot trigger card clearing", () => {
  assert.deepEqual(
    conditionPatch(request, {
      ...conditionsForm(request),
      adults: "2.0",
      rooms: "01",
    }),
    { set: {}, clear: [] },
  );
});

test("children selection preserves three distinct facts and uses clear for unknown", () => {
  assert.equal(conditionsForm(request).child_state, "unknown");
  const none = { ...request, child_ages: [] };
  const infant = { ...request, child_ages: [0] };
  assert.equal(conditionsForm(none).child_state, "none");
  assert.equal(conditionsForm(infant).child_state, "ages");
  assert.deepEqual(
    conditionPatch(request, {
      ...conditionsForm(request),
      child_state: "none",
    }),
    { set: { child_ages: [] }, clear: [] },
  );
  assert.deepEqual(
    conditionPatch(none, { ...conditionsForm(none), child_state: "unknown" }),
    { set: {}, clear: ["child_ages"] },
  );
  assert.deepEqual(
    conditionPatch(infant, {
      ...conditionsForm(infant),
      child_state: "unknown",
    }),
    { set: {}, clear: ["child_ages"] },
  );
  assert.deepEqual(
    conditionPatch(request, {
      ...conditionsForm(request),
      child_state: "ages",
      child_ages: "0",
    }),
    { set: { child_ages: [0] }, clear: [] },
  );
  for (const fact of [request, none, infant])
    assert.deepEqual(conditionPatch(fact, conditionsForm(fact)), {
      set: {},
      clear: [],
    });
});

test("children selected without ages cannot silently become none or invent infant zero", () => {
  for (const child_ages of ["", " ", "5,", ",5", "-1", "18", "1.5"]) {
    assert.throws(
      () =>
        conditionPatch(request, {
          ...conditionsForm(request),
          child_state: "ages",
          child_ages,
        }),
      /儿童年龄/,
    );
  }
  assert.throws(
    () =>
      conditionPatch(request, {
        ...conditionsForm(request),
        child_state: "invalid",
      }),
    /儿童/,
  );
});

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

test("lodging range preserves endpoints and trip budget while numeric no-op stays empty", () => {
  const capable = {
    ...request,
    lodging_budget: null,
    budget_relation: { status: "unknown" },
  } as unknown as RequestState;
  const form = conditionsForm(capable);
  assert.equal(form.lodging_basis, "");
  assert.equal(form.lodging_lower, "");
  assert.equal(form.lodging_upper, "");
  const update = {
    ...form,
    lodging_basis: "per_room_night",
    lodging_currency: "JPY",
    lodging_lower: "20000",
    lodging_upper: "30000",
  };
  assert.deepEqual(conditionPatch(capable, update), {
    set: {
      lodging_budget: {
        amount: { lower: "20000", upper: "30000" },
        basis: "per_room_night",
        currency: "JPY",
      },
    },
    clear: [],
  });
  const known = {
    ...capable,
    lodging_budget: {
      amount: { lower: "20000.00", upper: "30000.00" },
      basis: "per_room_night",
      currency: "JPY",
    },
  } as RequestState;

  assert.deepEqual(
    conditionPatch(known, {
      ...conditionsForm(known),
      lodging_lower: "20000",
      lodging_upper: "30000",
    }),
    { set: {}, clear: [] },
  );
  assert.deepEqual(
    conditionPatch(known, { ...conditionsForm(known), lodging_basis: "" }),
    { set: {}, clear: ["lodging_budget"] },
  );
});

test("lodging entry cannot silently discard facts when backend capability is missing", () => {
  assert.throws(
    () =>
      conditionPatch(request, {
        ...conditionsForm(request),
        lodging_basis: "total",
        lodging_currency: "JPY",
        lodging_upper: "30000",
      }),
    /住宿预算功能/,
  );
});

test("setting an amount clears explicit unlimited and preserves unrelated conditions", () => {
  const current = {
    ...request,
    lodging_budget_unlimited: true,
    lodging_budget: null,
    budget_relation: { status: "unknown" },
  } as RequestState;
  const form = {
    ...conditionsForm(current),
    lodging_basis: "per_room_night",
    lodging_currency: "JPY",
    lodging_upper: "8000",
  };
  const patch = conditionPatch(current, form);
  assert.ok(patch.clear.includes("lodging_budget_unlimited"));
  assert.equal(patch.set.lodging_budget?.amount.upper, "8000");
  assert.deepEqual(conditionPatch(current, conditionsForm(current)), {
    set: {},
    clear: [],
  });
});

test("an explicit form pace edit removes only a recognized hard pace", () => {
  const current = { ...request, hard_constraints: ["佛系", "不能登山"] };
  const form = conditionsForm(current);
  assert.equal(form.pace, "慢节奏");
  const patch = conditionPatch(current, { ...form, pace: "特种兵" });
  assert.deepEqual(patch.set.hard_constraints, ["不能登山"]);
  assert.deepEqual(patch.set.soft_constraints, ["少走路", "节奏：特种兵"]);
});

test("pace editing preserves prototype names in free hard conditions", () => {
  const hard_constraints = ["constructor", "toString", "__proto__", "不能登山"];
  const current = { ...request, hard_constraints };
  const form = conditionsForm(current);
  assert.equal(form.pace, "");
  const patch = conditionPatch(current, { ...form, pace: "标准" });
  assert.equal(patch.set.hard_constraints, undefined);
  assert.deepEqual(patch.set.soft_constraints, ["少走路", "节奏：标准"]);
  assert.deepEqual(current.hard_constraints, hard_constraints);
});

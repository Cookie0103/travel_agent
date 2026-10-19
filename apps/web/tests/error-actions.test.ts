/** Error banners only offer actions that can help for that kind of error. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError } from "../src/lib/api.ts";
import {
  classifyError,
  errorActions,
  errorKindFor,
} from "../src/lib/error-actions.ts";

test("classifyError separates revision conflicts, validation and other failures", () => {
  assert.equal(classifyError(new ApiError("x", 409, "conflict")), "conflict");
  assert.equal(classifyError(new ApiError("x", 422)), "validation");
  assert.equal(classifyError(new ApiError("x", 503)), "other");
  assert.equal(classifyError(new Error("network")), "other");
  assert.equal(classifyError("boom"), "other");
});

test("reconnect is only offered for stream errors while the run is still active", () => {
  assert.equal(errorActions("stream", true).reconnect, true);
  assert.equal(errorActions("stream", false).reconnect, false);
  for (const kind of ["conflict", "validation", "other", "run"] as const)
    assert.equal(errorActions(kind, true).reconnect, false);
});

test("refreshing latest state is hidden for validation errors only", () => {
  assert.equal(errorActions("validation", true).refresh, false);
  for (const kind of ["conflict", "stream", "other", "run"] as const)
    assert.equal(errorActions(kind, false).refresh, true);
});

test("stream-originated failures stay stream-kind even for 409/422, so reconnect is offered", () => {
  for (const status of [409, 422, 503])
    assert.equal(errorKindFor(new ApiError("x", status), true), "stream");
  assert.equal(errorKindFor(new ApiError("x", 409), false), "conflict");
  assert.equal(errorKindFor(new Error("n"), false), "other");
});

/** 后端 {code,message} 与 FastAPI 422 {detail:[...]} 都要变成可读错误并保留 code。 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { api, ApiError } from "../src/lib/api.ts";

async function failWith(status: number, body: unknown) {
  const original = globalThis.fetch;
  globalThis.fetch = async () => Response.json(body, { status });
  try {
    return await api("/x").then(
      () => assert.fail("expected failure"),
      (error: unknown) => error,
    );
  } finally {
    globalThis.fetch = original;
  }
}

test("ApiError keeps the backend error code", async () => {
  const error = await failWith(409, {
    code: "conflict",
    message: "版本已变化",
  });
  assert.ok(error instanceof ApiError);
  assert.equal(error.status, 409);
  assert.equal(error.code, "conflict");
  assert.equal(error.message, "版本已变化");
});

test("FastAPI 422 detail list becomes readable Chinese naming the fields", async () => {
  const error = await failWith(422, {
    detail: [
      {
        loc: ["body", "expected_revision"],
        msg: "Input should be a valid integer",
        type: "int_parsing",
      },
      {
        loc: ["body", "text"],
        msg: "String too short",
        type: "string_too_short",
      },
    ],
  });
  assert.ok(error instanceof ApiError);
  assert.equal(error.status, 422);
  assert.match(error.message, /expected_revision/);
  assert.match(error.message, /text/);
  assert.doesNotMatch(error.message, /Input should be/);
});

test("non-JSON failures fall back to the status text", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response("bad gateway", { status: 502 });
  try {
    await assert.rejects(api("/x"), (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.code, undefined);
      assert.match(error.message, /502/);
      return true;
    });
  } finally {
    globalThis.fetch = original;
  }
});

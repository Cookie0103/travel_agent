/** 后端 {code,message} 要保留 code；非 JSON 失败回退到状态码文案。 */
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

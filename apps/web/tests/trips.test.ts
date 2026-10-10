/** R01/R03: one identity can create independent trips; the outbox stays bound to its owner. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { createTrip, readTripHistory } from "../src/lib/api.ts";
import {
  persistIdentity,
  restoreIdentity,
  forgetIdentity,
  pendingFor,
} from "../src/lib/identity-storage.ts";

class MemoryStorage {
  values = new Map<string, string>();
  get length() {
    return this.values.size;
  }
  key(index: number) {
    return [...this.values.keys()][index] ?? null;
  }
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
  removeItem(key: string) {
    this.values.delete(key);
  }
}
const first = { token: "synthetic-owner", session_id: "kyoto" };
const pending = {
  client_message_id: "synthetic-id",
  text: "京都三天",
  mode: "offline" as const,
};

test("identity persistence contains only token and session; switching never transfers a message", () => {
  const local = new MemoryStorage(),
    tab = new MemoryStorage();
  persistIdentity(local, tab, {
    ...first,
    pending_message: pending,
    plan_id: "formal",
    run_id: "run",
  });
  assert.deepEqual(JSON.parse(local.getItem("travel-demo-v2")!), first);
  assert.deepEqual(restoreIdentity(local, tab)?.pending_message, pending);
  const second = { ...first, session_id: "sapporo" };
  persistIdentity(local, tab, second);
  assert.equal(restoreIdentity(local, tab)?.pending_message, undefined);
  assert.deepEqual(pendingFor(tab, first), pending);
  assert.equal(
    pendingFor(tab, { ...first, token: "another-owner" }),
    undefined,
  );
});

test("legacy pending migrates once; another tab does not inherit or retry it", () => {
  const local = new MemoryStorage(),
    tab = new MemoryStorage();
  local.setItem(
    "travel-demo-v2",
    JSON.stringify({
      ...first,
      pending_message: pending,
      plan_id: "plan",
      run_id: "run",
      user_id: "old-user",
      expires_at: "old-time",
    }),
  );
  assert.deepEqual(restoreIdentity(local, tab)?.pending_message, pending);
  assert.deepEqual(JSON.parse(local.getItem("travel-demo-v2")!), first);
  assert.equal(
    restoreIdentity(local, new MemoryStorage())?.pending_message,
    undefined,
  );
});

test("accepted message clears its outbox; unauthorized identity invalidates all its trips", () => {
  const local = new MemoryStorage(),
    tab = new MemoryStorage();
  persistIdentity(local, tab, { ...first, pending_message: pending });
  persistIdentity(local, tab, first);
  assert.equal(pendingFor(tab, first), undefined);
  persistIdentity(local, tab, { ...first, pending_message: pending });
  persistIdentity(local, tab, {
    ...first,
    session_id: "sapporo",
    pending_message: pending,
  });
  forgetIdentity(local, tab);
  assert.equal(restoreIdentity(local, tab), undefined);
  assert.equal(pendingFor(tab, first), undefined);
  assert.equal(pendingFor(tab, { ...first, session_id: "sapporo" }), undefined);
});

test("malformed storage cannot invent an identity or submit an obsolete live message", () => {
  const local = new MemoryStorage(),
    tab = new MemoryStorage();
  local.setItem("travel-demo-v2", "{");
  assert.equal(restoreIdentity(local, tab), undefined);
  local.setItem(
    "travel-demo-v2",
    JSON.stringify({ ...first, pending_message: { ...pending, mode: "live" } }),
  );
  assert.equal(restoreIdentity(local, tab)?.pending_message, undefined);
});

test("new trip uses the existing bearer without login and history uses bounded pages", async () => {
  const original = globalThis.fetch;
  const paths: string[] = [];
  globalThis.fetch = async (input, options) => {
    paths.push(String(input));
    assert.equal(
      new Headers(options?.headers).get("Authorization"),
      "Bearer synthetic-owner",
    );
    if (paths.length === 1) {
      assert.equal(options?.method, "POST");
      return Response.json({
        session_id: "sapporo",
        created_at: "2026-10-08T00:00:00Z",
      });
    }
    assert.equal(options?.method, "GET");
    return Response.json({ items: [], next_cursor: null });
  };
  try {
    assert.equal((await createTrip(first.token)).session_id, "sapporo");
    await readTripHistory(first.token, "earlier");
    assert.deepEqual(paths, [
      "/api/sessions",
      "/api/sessions?limit=20&cursor=earlier",
    ]);
  } finally {
    globalThis.fetch = original;
  }
});

test("an expired old tab cannot erase a newer identity saved by another tab", () => {
  const local = new MemoryStorage(),
    tab = new MemoryStorage();
  persistIdentity(local, tab, { ...first, pending_message: pending });
  const newer = { token: "new-owner", session_id: "new-trip" };
  persistIdentity(local, new MemoryStorage(), newer);
  forgetIdentity(local, tab, first.token);
  assert.deepEqual(restoreIdentity(local, new MemoryStorage()), newer);
  assert.equal(pendingFor(tab, first), undefined);
});

test("old API identifies unsupported history instead of pretending it is an empty trip list", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () =>
    Response.json({ message: "Not Found" }, { status: 404 });
  try {
    await assert.rejects(readTripHistory(first.token), /暂不支持旅行历史/);
  } finally {
    globalThis.fetch = original;
  }
});

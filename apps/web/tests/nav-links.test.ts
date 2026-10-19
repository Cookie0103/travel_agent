/** Navigation entries are plain data: the guide list is reachable and the current page is marked. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { navLinks, isCurrentNav } from "../src/lib/nav-links.ts";

test("nav offers conversation, trips and guides", () => {
  assert.deepEqual(
    navLinks.map((link) => link.href),
    ["/", "/plans", "/articles"],
  );
  assert.ok(navLinks.some((link) => link.label === "攻略与来源"));
});

test("current page matching is exact for home and prefix-based for sections", () => {
  assert.equal(isCurrentNav("/", "/"), true);
  assert.equal(isCurrentNav("/", "/plans"), false);
  assert.equal(isCurrentNav("/articles", "/articles"), true);
  assert.equal(isCurrentNav("/articles", "/articles/kyoto-guide"), true);
  assert.equal(isCurrentNav("/articles", "/articles-other"), false);
  assert.equal(isCurrentNav("/plans", "/articles"), false);
});

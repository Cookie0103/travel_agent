/** Chat page scrolls inside its two panes only; the page itself must not grow. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const css = readFileSync("src/app/globals.css", "utf8");
const rule = (selector: string) => {
  const match = css.match(
    new RegExp(`\n  ${selector.replace(".", "\.")} \{([^}]*)\}`),
  );
  assert.ok(match, `${selector} rule missing`);
  return match[1];
};

test("scroll panes contain absolutely positioned descendants", () => {
  // sr-only 文本和图片角标若以页面为包含块，会把整页撑高到可滚动。
  for (const selector of [".chat-scroll", ".trip-panel"]) {
    const body = rule(selector);
    assert.match(body, /overflow-y: auto/);
    assert.match(body, /position: relative/);
  }
  assert.match(rule(".chat-main"), /overflow: hidden/);
});

/** Model answers render as data: bold/lists/https links only, never raw HTML. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseBlocks, parseInline } from "../src/lib/markdown.ts";

test("bold and https link become structured inline parts", () => {
  assert.deepEqual(parseInline("a **b** [c](https://x.jp/p)"), [
    { type: "text", text: "a " },
    { type: "bold", text: "b" },
    { type: "text", text: " " },
    { type: "link", text: "c", href: "https://x.jp/p" },
  ]);
});

test("bullet and numbered lines group into ul / ol, blank line splits paragraphs", () => {
  assert.deepEqual(parseBlocks("- 甲\n* 乙\n\n1. 一\n2) 二\n普通\n续行"), [
    { type: "ul", items: ["甲", "乙"] },
    { type: "ol", items: ["一", "二"] },
    { type: "p", items: ["普通", "续行"] },
  ]);
});

test("script tags stay literal text", () => {
  const blocks = parseBlocks("<script>alert(1)</script>");
  assert.deepEqual(blocks, [
    { type: "p", items: ["<script>alert(1)</script>"] },
  ]);
  assert.deepEqual(parseInline(blocks[0].items[0]), [
    { type: "text", text: "<script>alert(1)</script>" },
  ]);
});

test("javascript: and http: links are not rendered as links", () => {
  for (const url of ["javascript:alert(1)", "http://x.jp"]) {
    const parts = parseInline(`[hi](${url})`);
    assert.ok(parts.every((part) => part.type !== "link"));
    assert.equal(parts.map((part) => part.text).join(""), `[hi](${url})`);
  }
});

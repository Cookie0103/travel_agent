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
  assert.ok(blocks[0].type === "p");
  assert.deepEqual(parseInline(blocks[0].items[0]), [
    { type: "text", text: "<script>alert(1)</script>" },
  ]);
});

test("table headers, rows and alignment are structured between normal blocks", () => {
  const blocks = parseBlocks(
    "前言\n\n| 城市 | 预算 | 节奏 |\n| :--- | ---: | :---: |\n| 京都 | **50000** | 慢 |\n| 大阪 | 未知 | 标准 |\n\n后续",
  );
  assert.equal(blocks.length, 3);
  const table = blocks[1];
  assert.ok(table.type === "table");
  assert.deepEqual(table.headers, ["城市", "预算", "节奏"]);
  assert.deepEqual(table.alignments, ["left", "right", "center"]);
  assert.deepEqual(table.rows, [
    ["京都", "**50000**", "慢"],
    ["大阪", "未知", "标准"],
  ]);
});

test("escaped pipes stay in cells; bad or inconsistent tables never lose text", () => {
  const table = parseBlocks(String.raw`城市\|区域 | 金额
--- | ---
京都\|东侧 | 50000`)[0];
  assert.ok(table.type === "table");
  assert.deepEqual(table.headers, ["城市|区域", "金额"]);
  assert.deepEqual(table.rows, [["京都|东侧", "50000"]]);
  for (const text of [
    "| 城市 | 金额 |\n| --- |\n| 京都 | 50000 |",
    "| 城市 | 金额 |\n| --- | --- |\n| 京都 | 50000 | 多余 |",
    "只有 | 竖线",
  ]) {
    const blocks = parseBlocks(text);
    assert.ok(blocks.every((block) => block.type !== "table"));
    assert.equal(blocks.flatMap((block) => block.items).join("\n"), text);
  }
});

test("table cells reuse safe inline data for HTML and link schemes", () => {
  const table = parseBlocks(
    "| 内容 | 来源 |\n| --- | --- |\n| <img src=x onerror=alert(1)> | [坏链接](javascript:alert(1)) |\n| <script>alert(1)</script> | [来源](https://example.com) |",
  )[0];
  assert.ok(table.type === "table");
  assert.deepEqual(parseInline(table.rows[0][0]), [
    { type: "text", text: "<img src=x onerror=alert(1)>" },
  ]);
  assert.ok(
    parseInline(table.rows[0][1]).every((part) => part.type !== "link"),
  );
  assert.deepEqual(parseInline(table.rows[1][0]), [
    { type: "text", text: "<script>alert(1)</script>" },
  ]);
  assert.ok(parseInline(table.rows[1][1]).some((part) => part.type === "link"));
});

test("javascript: and http: links are not rendered as links", () => {
  for (const url of ["javascript:alert(1)", "http://x.jp"]) {
    const parts = parseInline(`[hi](${url})`);
    assert.ok(parts.every((part) => part.type !== "link"));
    assert.equal(parts.map((part) => part.text).join(""), `[hi](${url})`);
  }
});

test("lists immediately after a table retain their original block type", () => {
  for (const [line, type] of [
    ["- 下一步 | 补日期", "ul"],
    ["1. 下一步 | 补日期", "ol"],
  ]) {
    const blocks = parseBlocks(
      `| 城市 | 金额 |\n| --- | --- |\n| 京都 | 50000 |\n${line}`,
    );
    assert.equal(blocks.length, 2);
    assert.ok(blocks[0].type === "table");
    assert.deepEqual(blocks[0].rows, [["京都", "50000"]]);
    assert.deepEqual(blocks[1], { type, items: ["下一步 | 补日期"] });
  }
});

test("an inconsistent table falls back as one literal span without reparsing its body", () => {
  const text = "H1|H2\n---|---\na|b|c\n---|---|---\nx|y|z";
  assert.deepEqual(parseBlocks(text), [{ type: "p", items: text.split("\n") }]);
});

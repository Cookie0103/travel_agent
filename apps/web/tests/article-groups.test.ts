/** Guide browsing keeps every section and groups it under its destination. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { groupByCity, sectionTitle } from "../src/lib/article-groups.ts";

test("sections group by city field, falling back to the title prefix", () => {
  const groups = groupByCity([
    { city: "京都", title: "京都 · 巴士" },
    { city: "", title: "大阪 · 地铁" },
    { city: "京都", title: "京都 · 私鐵" },
    { city: "", title: "无前缀" },
  ]);
  assert.deepEqual(
    groups.map((g) => [g.city, g.items.length]),
    [
      ["京都", 2],
      ["大阪", 1],
      ["其他", 1],
    ],
  );
  assert.equal(sectionTitle({ city: "京都", title: "京都 · 巴士" }), "巴士");
  assert.equal(sectionTitle({ city: "京都", title: "伏见" }), "伏见");
});

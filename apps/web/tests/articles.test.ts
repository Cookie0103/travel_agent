/** Public attribution links must not execute scripts or turn snapshots into active HTML. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { sourceHref } from "../src/lib/api.ts";

test("snapshot attribution only links valid HTTPS URLs", () => {
  assert.equal(
    sourceHref("https://zh.wikivoyage.org/w/index.php?oldid=42"),
    "https://zh.wikivoyage.org/w/index.php?oldid=42",
  );
  for (const value of [
    "javascript:alert(1)",
    "data:text/html,<script>x</script>",
    "http://example.com",
    "not-a-url",
    "//example.com",
  ])
    assert.equal(sourceHref(value), undefined);
});

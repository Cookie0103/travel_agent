/** C5: every user-visible timestamp uses Asia/Tokyo regardless of the browser zone. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { formatTokyo } from "../src/lib/format-time.ts";
import { providerLabel, sourceNames } from "../src/lib/articles.ts";

test("timestamps render in Tokyo time and keep unparsable input visible", () => {
  assert.equal(formatTokyo("2026-11-02T15:30:00Z"), "2026/11/03 00:30");
  assert.equal(formatTokyo("2026-11-03T00:30:00+09:00"), "2026/11/03 00:30");
  assert.equal(formatTokyo("not-a-time"), "not-a-time");
});

test("article provenance comes from the data, not a hard-coded Kyoto/Wikivoyage label", () => {
  assert.equal(providerLabel("wikivoyage"), "Wikivoyage");
  assert.equal(providerLabel("osm"), "OpenStreetMap");
  const article = (provider: string) => ({ source: { provider } }) as never;
  assert.equal(sourceNames([article("wikivoyage")]), "Wikivoyage");
  assert.equal(
    sourceNames([article("wikivoyage"), article("osm"), article("wikivoyage")]),
    "Wikivoyage、OpenStreetMap",
  );
  assert.equal(sourceNames([]), "");
});

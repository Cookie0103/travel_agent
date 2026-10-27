/** /models 失败不能伪装成“只有离线可用”，要明确告诉用户后端不可用。 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  offlineOption,
  loadModels,
  type ModelOption,
} from "../src/lib/models.ts";

test("successful load returns the server options without an error", async () => {
  const live: ModelOption = {
    id: "claude",
    label: "Claude",
    available: true,
    reason: null,
  };
  const result = await loadModels(async () => [offlineOption, live]);
  assert.deepEqual(result.options, [offlineOption, live]);
  assert.equal(result.error, "");
});

test("failed load keeps offline selectable but reports the backend as unavailable", async () => {
  const result = await loadModels(async () => {
    throw new TypeError("fetch failed");
  });
  assert.deepEqual(result.options, [offlineOption]);
  assert.match(result.error, /无法获取模型/);
});

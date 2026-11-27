// pi (pi-agent-core)：stdin {prompt, baseUrl, model, systemPrompt, tools, toolUrl, maxSteps} → stdout {text}
import { Agent } from "@earendil-works/pi-agent-core";
import { createModels } from "@earendil-works/pi-ai";
import { deepseekProvider } from "@earendil-works/pi-ai/providers/deepseek";

const input = JSON.parse(await new Promise((ok) => {
  let s = "";
  process.stdin.on("data", (d) => (s += d));
  process.stdin.on("end", () => ok(s));
}));

const models = createModels();
models.setProvider(deepseekProvider());
const catalog = models.getModel("deepseek", input.model);
if (!catalog) throw new Error(`model not found: ${input.model}`);
const model = { ...catalog, baseUrl: input.baseUrl }; // 走计量代理

const tools = input.tools.map((spec) => ({
  ...spec,
  label: spec.name,
  execute: async (_id, params) => {
    const res = await fetch(input.toolUrl, {
      method: "POST",
      body: JSON.stringify({ name: spec.name, args: params }),
    });
    const r = await res.json();
    if (!r.ok) throw new Error(r.error); // pi惯用法：抛错 → isError的toolResult回给模型
    return { content: [{ type: "text", text: r.text }], details: {} };
  },
}));

const agent = new Agent({
  initialState: { systemPrompt: input.systemPrompt, model, thinkingLevel: "off", tools },
  streamFn: models.streamSimple.bind(models),
});
let steps = 0;
agent.subscribe((e) => {
  if (e.type === "message_end" && e.message.role === "assistant" && ++steps >= input.maxSteps) {
    agent.abort?.();
  }
});
await agent.prompt(input.prompt);
await agent.waitForIdle();
const last = agent.state.messages.filter((m) => m.role === "assistant").at(-1);
if (last?.stopReason === "error") throw new Error(last.errorMessage ?? "model error");
const text = last ? last.content.filter((c) => c.type === "text").map((c) => c.text).join("") : "";
process.stdout.write(JSON.stringify({ text }));

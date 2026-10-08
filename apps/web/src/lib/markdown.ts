/** Tiny, dependency-free Markdown subset for model answers; output is data, never HTML. */
import { sourceHref } from "./api.ts";

export type Block = { type: "p" | "ul" | "ol"; items: string[] };
export type Inline =
  | { type: "text"; text: string }
  | { type: "bold"; text: string }
  | { type: "link"; text: string; href: string };

const UL = /^\s*[-*•]\s+/;
const OL = /^\s*\d+[.)、]\s+/;

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) {
      blocks.push({ type: "p", items: [] });
      continue;
    }
    const type = UL.test(line) ? "ul" : OL.test(line) ? "ol" : "p";
    const item =
      type === "p" ? line : line.replace(type === "ul" ? UL : OL, "");
    const last = blocks[blocks.length - 1];
    if (last && last.type === type && last.items.length) last.items.push(item);
    else if (last && last.type === "p" && !last.items.length && type === "p")
      last.items.push(item);
    else blocks.push({ type, items: [item] });
  }
  return blocks.filter((block) => block.items.length);
}

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  const token = /\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  for (const m of text.matchAll(token)) {
    if (m.index > last)
      out.push({ type: "text", text: text.slice(last, m.index) });
    const href = m[3] ? sourceHref(m[3]) : undefined;
    if (m[1]) out.push({ type: "bold", text: m[1] });
    else if (href) out.push({ type: "link", text: m[2], href });
    else out.push({ type: "text", text: m[0] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ type: "text", text: text.slice(last) });
  return out;
}

/** Tiny, dependency-free Markdown subset for model answers; output is data, never HTML. */
import { sourceHref } from "./api.ts";

export type Block =
  | { type: "p" | "ul" | "ol"; items: string[] }
  | {
      type: "table";
      headers: string[];
      rows: string[][];
      alignments: ("left" | "center" | "right" | undefined)[];
    };
export type Inline =
  | { type: "text"; text: string }
  | { type: "bold"; text: string }
  | { type: "link"; text: string; href: string };

const UL = /^\s*[-*•]\s+/;
const OL = /^\s*\d+[.)、]\s+/;

function cells(line: string): string[] {
  const parts: string[] = [];
  let cell = "";
  for (let i = 0; i < line.length; i++) {
    if (line[i] === "\\" && line[i + 1] === "|") {
      cell += "|";
      i++;
    } else if (line[i] === "|") {
      parts.push(cell.trim());
      cell = "";
    } else cell += line[i];
  }
  parts.push(cell.trim());
  if (line.trim().startsWith("|")) parts.shift();
  if (parts.length > 1 && parts[parts.length - 1] === "") parts.pop();
  return parts;
}

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  const lines = text.split(/\r?\n/);
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    const header = cells(line);
    const separator =
      lines[index + 1] === undefined ? [] : cells(lines[index + 1]);
    if (
      line.includes("|") &&
      header.length &&
      header.length === separator.length &&
      separator.every((part) => /^:?-{3,}:?$/.test(part))
    ) {
      const rows: string[][] = [];
      let end = index + 2;
      while (
        end < lines.length &&
        lines[end].trim() &&
        lines[end].includes("|") &&
        !UL.test(lines[end]) &&
        !OL.test(lines[end])
      )
        rows.push(cells(lines[end++]));
      if (rows.every((row) => row.length === header.length)) {
        blocks.push({
          type: "table",
          headers: header,
          rows,
          alignments: separator.map((part) =>
            part.startsWith(":")
              ? part.endsWith(":")
                ? "center"
                : "left"
              : part.endsWith(":")
                ? "right"
                : undefined,
          ),
        });
      } else blocks.push({ type: "p", items: lines.slice(index, end) });
      index = end - 1;
      continue;
    }
    if (!line.trim()) {
      blocks.push({ type: "p", items: [] });
      continue;
    }
    const type = UL.test(line) ? "ul" : OL.test(line) ? "ol" : "p";
    const item =
      type === "p" ? line : line.replace(type === "ul" ? UL : OL, "");
    const last = blocks[blocks.length - 1];
    if (
      last &&
      last.type !== "table" &&
      last.type === type &&
      last.items.length
    )
      last.items.push(item);
    else if (last && last.type === "p" && !last.items.length && type === "p")
      last.items.push(item);
    else blocks.push({ type, items: [item] });
  }
  return blocks.filter((block) => block.type === "table" || block.items.length);
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

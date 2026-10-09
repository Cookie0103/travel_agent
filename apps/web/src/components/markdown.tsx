/** Renders the safe Markdown subset as React elements (no raw HTML). */
import { Fragment } from "react";
import { parseBlocks, parseInline } from "@/lib/markdown";

function Inline({ text }: { text: string }) {
  return parseInline(text).map((part, index) =>
    part.type === "bold" ? (
      <strong key={index}>{part.text}</strong>
    ) : part.type === "link" ? (
      <a key={index} href={part.href} target="_blank" rel="noopener noreferrer">
        {part.text}
      </a>
    ) : (
      <Fragment key={index}>{part.text}</Fragment>
    ),
  );
}

export function Markdown({ text }: { text: string }) {
  return parseBlocks(text).map((block, index) => {
    if (block.type === "table")
      return (
        <div className="markdown-table" key={index}>
          <table>
            <thead>
              <tr>
                {block.headers.map((cell, column) => (
                  <th
                    scope="col"
                    key={column}
                    style={{ textAlign: block.alignments[column] }}
                  >
                    <Inline text={cell} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, column) => (
                    <td
                      key={column}
                      style={{ textAlign: block.alignments[column] }}
                    >
                      <Inline text={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    const items = block.items.map((item, i) =>
      block.type === "p" ? (
        <Fragment key={i}>
          {i > 0 && <br />}
          <Inline text={item} />
        </Fragment>
      ) : (
        <li key={i}>
          <Inline text={item} />
        </li>
      ),
    );
    if (block.type === "ul") return <ul key={index}>{items}</ul>;
    if (block.type === "ol") return <ol key={index}>{items}</ol>;
    return <p key={index}>{items}</p>;
  });
}

/** One round's memory cards: pick on each, then one confirmation records them all together. */
"use client";
import { useState } from "react";
import type { Choice } from "@/lib/api";
import { choiceDisabled, type Pick } from "@/lib/choices";
import { Button } from "./ui/button";
import { useClock } from "./results";

export function MemoryChoices({
  cards,
  busy,
  sessionId,
  revision,
  submit,
}: {
  cards: Choice[];
  busy: boolean;
  sessionId?: string;
  revision?: number;
  submit: (picks: Pick[]) => void;
}) {
  const now = useClock();
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const open = (card: Choice) =>
    !choiceDisabled(card, false, sessionId, revision, now);
  const chosen = cards.flatMap((card) =>
    open(card) && picked[card.choice_id!]
      ? [{ card, optionId: picked[card.choice_id!] }]
      : [],
  );
  return (
    <section className="space-y-4 rounded-xl border border-border bg-bg-subtle p-4">
      {cards.map((card) => (
        <fieldset
          key={card.choice_id}
          disabled={!open(card)}
          className="space-y-2"
        >
          <legend className="font-medium">{card.question}</legend>
          <div className="flex flex-wrap gap-2">
            {card.options.map((option) => {
              const on =
                (card.answered_option_id ?? picked[card.choice_id!]) ===
                option.option_id;
              return (
                <Button
                  key={option.option_id}
                  type="button"
                  variant={on ? "default" : "outline"}
                  aria-pressed={on}
                  onClick={() =>
                    setPicked((old) => ({
                      ...old,
                      [card.choice_id!]: option.option_id,
                    }))
                  }
                >
                  {option.label}
                </Button>
              );
            })}
          </div>
          {card.answered_option_id ? (
            <p className="small muted">已记录你的选择</p>
          ) : card.stale ? (
            <p className="small muted">条件已变化，请按当前条件重新选择。</p>
          ) : null}
        </fieldset>
      ))}
      {cards.some(open) && (
        <>
          <Button
            type="button"
            disabled={busy}
            onClick={() => {
              if (!chosen.length) return setNote("请至少选择一条再提交。");
              setNote("");
              submit(chosen);
            }}
          >
            确认并继续
          </Button>
          {(note || busy) && (
            <p className="small muted">
              {note || "正在处理上一条消息，稍后即可提交。"}
            </p>
          )}
        </>
      )}
    </section>
  );
}

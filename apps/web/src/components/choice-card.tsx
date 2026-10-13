"use client";
import type { Choice } from "@/lib/api";
import { choiceDisabled } from "@/lib/choices";
import { Button } from "./ui/button";
import { useClock } from "./results";

export function ChoiceCard({
  card,
  busy,
  sessionId,
  revision,
  select,
}: {
  card: Choice;
  busy: boolean;
  sessionId?: string;
  revision?: number;
  select: (optionId: string) => void;
}) {
  const now = useClock();
  const disabled = choiceDisabled(card, busy, sessionId, revision, now);
  const stale =
    card.stale ||
    card.expected_revision !== revision ||
    !!(card.expires_at && now > 0 && Date.parse(card.expires_at) <= now);
  return (
    <section
      className="space-y-3 rounded-xl border border-border bg-bg-subtle p-4"
      aria-label={card.question}
    >
      <p className="font-medium">{card.question}</p>
      <div className="flex flex-wrap gap-2">
        {card.options.map((option) => (
          <Button
            key={option.option_id}
            type="button"
            variant={
              card.answered_option_id === option.option_id
                ? "default"
                : "outline"
            }
            aria-pressed={card.answered_option_id === option.option_id}
            disabled={disabled}
            onClick={() => select(option.option_id)}
          >
            {option.label}
          </Button>
        ))}
      </div>
      {card.answered_option_id ? (
        <p className="small muted">已记录你的选择</p>
      ) : stale ? (
        <p className="small muted">条件已变化，请按当前条件重新选择。</p>
      ) : null}
    </section>
  );
}

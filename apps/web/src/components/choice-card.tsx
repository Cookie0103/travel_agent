"use client";
import { useId, useState } from "react";
import type { Choice } from "@/lib/api";
import {
  assignOf,
  choiceDisabled,
  formOf,
  TEXT_MAX,
  type FormAnswers,
} from "@/lib/choices";
import { Button } from "./ui/button";
import { useClock } from "./results";
import { ChoiceForm } from "./choice-form";

/** hotel_assign: confirm, or deny and say which city; "dismiss" skips the hotel. */
function AssignCard({
  card,
  disabled,
  stale,
  select,
}: {
  card: Choice;
  disabled: boolean;
  stale: boolean;
  select: (optionId: string, answers?: FormAnswers) => void;
}) {
  const id = useId();
  const [asking, setAsking] = useState(false);
  const [city, setCity] = useState("");
  const answered = !!card.answered_option_id;
  const typed = city.trim();
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
              card.answered_option_id === option.option_id ||
              (asking && option.option_id === "deny")
                ? "default"
                : "outline"
            }
            aria-pressed={
              card.answered_option_id === option.option_id ||
              (asking && option.option_id === "deny")
            }
            disabled={disabled}
            onClick={() =>
              option.option_id === "deny"
                ? setAsking((value) => !value)
                : select(option.option_id)
            }
          >
            {option.label}
          </Button>
        ))}
      </div>
      {asking && !answered && (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!disabled && typed) select("deny", { city: [typed] });
          }}
        >
          <label htmlFor={id} className="text-sm">
            是哪个城市？
          </label>
          <input
            id={id}
            type="text"
            className="min-w-40 rounded-lg border border-border bg-bg px-3 py-2 text-sm"
            maxLength={TEXT_MAX}
            placeholder="如 大阪"
            value={city}
            disabled={disabled}
            onChange={(event) => setCity(event.target.value)}
          />
          <Button type="submit" disabled={disabled || !typed}>
            提交城市
          </Button>
        </form>
      )}
      {answered ? (
        <p className="small muted">已记录你的选择</p>
      ) : stale ? (
        <p className="small muted">条件已变化，请按当前条件重新选择。</p>
      ) : null}
    </section>
  );
}

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
  select: (optionId: string, answers?: FormAnswers) => void;
}) {
  const now = useClock();
  const disabled = choiceDisabled(card, busy, sessionId, revision, now);
  const stale =
    card.stale ||
    card.expected_revision !== revision ||
    !!(card.expires_at && now > 0 && Date.parse(card.expires_at) <= now);
  if (formOf(card))
    return (
      <ChoiceForm
        key={`${card.choice_id}:${card.answered_option_id ?? "pending"}`}
        card={card}
        disabled={disabled}
        stale={stale}
        confirm={(answers) => select("confirm", answers)}
      />
    );
  if (card.kind === "hotel_assign" && assignOf(card))
    return (
      <AssignCard
        key={`${card.choice_id}:${card.answered_option_id ?? "pending"}`}
        card={card}
        disabled={disabled}
        stale={stale}
        select={select}
      />
    );
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

/** Generic server-driven form: choose per group, then one explicit confirmation submits everything. */
"use client";
import { useId, useState } from "react";
import type { Choice } from "@/lib/api";
import {
  formOf,
  validAnswers,
  type FormAnswers,
  type FormGroup,
} from "@/lib/choices";
import { Button } from "./ui/button";

export function ChoiceGroup({
  group,
  value,
  disabled,
  onChange,
}: {
  group: FormGroup;
  value: string[];
  disabled: boolean;
  onChange: (value: string[]) => void;
}) {
  const toggle = (id: string) =>
    onChange(
      value.includes(id)
        ? value.filter((v) => v !== id)
        : group.multi
          ? [...value, id]
          : [id],
    );
  return (
    <fieldset disabled={disabled} className="space-y-2">
      <legend className="mb-2 text-sm font-medium">{group.label}</legend>
      <div className="flex flex-wrap gap-2">
        {group.options.map((option) => (
          <Button
            key={option.option_id}
            type="button"
            variant={value.includes(option.option_id) ? "default" : "outline"}
            aria-pressed={value.includes(option.option_id)}
            onClick={() => toggle(option.option_id)}
          >
            {option.label}
          </Button>
        ))}
      </div>
    </fieldset>
  );
}

function TimesGroup({
  group,
  answers,
  disabled,
  answered,
  set,
}: {
  group: FormGroup;
  answers: FormAnswers;
  disabled: boolean;
  answered: boolean;
  set: (patch: Record<string, string[] | undefined>) => void;
}) {
  const id = useId();
  const fixed = `${group.key}_corrected`;
  const state = answers[group.key]?.[0];
  return (
    <fieldset disabled={disabled} className="space-y-3">
      <legend className="mb-2 text-sm font-medium">{group.label}</legend>
      {(group.shown ?? []).map((text, index) => (
        <p className="text-sm whitespace-pre-wrap" key={index}>
          {text}
        </p>
      ))}
      {!answered && (
        <>
          <div className="flex gap-2">
            {(["yes", "no"] as const).map((v) => (
              <Button
                key={v}
                type="button"
                variant={state === v ? "default" : "outline"}
                aria-pressed={state === v}
                onClick={() =>
                  set(
                    state === v
                      ? { [group.key]: undefined, [fixed]: undefined }
                      : {
                          [group.key]: [v],
                          [fixed]: v === "no" ? [""] : undefined,
                        },
                  )
                }
              >
                {v === "yes" ? "是" : "不是"}
              </Button>
            ))}
          </div>
          {state === "no" && (
            <div className="space-y-2">
              <label htmlFor={id} className="text-sm">
                请写出正确的抵达／离开日期和时间
              </label>
              <textarea
                id={id}
                className="min-h-24 w-full rounded-lg border border-border bg-bg p-3 text-sm"
                maxLength={200}
                placeholder="例如：10月20日10点到，10月22日晚上9点走"
                value={answers[fixed]?.[0] ?? ""}
                onChange={(event) => set({ [fixed]: [event.target.value] })}
              />
            </div>
          )}
        </>
      )}
    </fieldset>
  );
}

export function ChoiceForm({
  card,
  disabled,
  stale,
  confirm,
}: {
  card: Choice;
  disabled: boolean;
  stale: boolean;
  confirm: (answers: FormAnswers) => void;
}) {
  const groups = formOf(card) ?? [];
  const answered = !!card.answered_option_id;
  const [answers, setAnswers] = useState<FormAnswers>(() =>
    Object.fromEntries(
      groups.filter((g) => g.selected?.length).map((g) => [g.key, g.selected!]),
    ),
  );
  const set = (patch: Record<string, string[] | undefined>) =>
    setAnswers((old) => {
      const next: FormAnswers = { ...old };
      for (const [key, value] of Object.entries(patch))
        if (value) next[key] = value;
        else delete next[key];
      return next;
    });
  const ready = validAnswers(card, answers);
  return (
    <form
      aria-label={card.question}
      className="space-y-5 rounded-xl border border-border bg-bg-subtle p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!disabled && ready) confirm(answers);
      }}
    >
      <p className="font-medium">{card.question}</p>
      {groups.map((group) =>
        group.kind === "times" ? (
          <TimesGroup
            key={group.key}
            group={group}
            answers={answers}
            disabled={disabled}
            answered={answered}
            set={set}
          />
        ) : (
          <ChoiceGroup
            key={group.key}
            group={group}
            value={answers[group.key] ?? []}
            disabled={disabled}
            onChange={(value) => set({ [group.key]: value })}
          />
        ),
      )}
      {answered ? (
        <p className="small muted">已确认</p>
      ) : stale ? (
        <p className="small muted">条件已变化，请按当前条件重新确认。</p>
      ) : (
        <>
          <Button type="submit" disabled={disabled || !ready}>
            确认并继续
          </Button>
          {!ready && (
            <p className="small muted">
              {answers.times?.[0] === "no"
                ? "请写出正确的抵达／离开时间后提交。"
                : "选好上面的选项就能提交；也可以在对话框里补充。"}
            </p>
          )}
        </>
      )}
    </form>
  );
}

/** Generic server-driven form: choose per group, then one explicit confirmation submits everything. */
"use client";
import { useId, useState } from "react";
import type { Choice } from "@/lib/api";
import {
  cleanAnswers,
  formOf,
  setGroupOption,
  setGroupText,
  TEXT_MAX,
  textKey,
  validAnswers,
  type FormAnswers,
  type FormGroup,
} from "@/lib/choices";
import { Button } from "./ui/button";

function ChoiceGroup({
  group,
  answers,
  disabled,
  update,
}: {
  group: FormGroup;
  answers: FormAnswers;
  disabled: boolean;
  update: (next: FormAnswers) => void;
}) {
  const id = useId();
  const value = answers[group.key] ?? [];
  const text = answers[textKey(group.key)]?.[0] ?? "";
  const hint = `${id}-hint`;
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
            onClick={() =>
              update(setGroupOption(answers, group, option.option_id))
            }
          >
            {option.label}
          </Button>
        ))}
      </div>
      {group.allow_text && (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={`${id}-text`} className="text-sm">
            或自己填写
          </label>
          <input
            id={`${id}-text`}
            type="text"
            className="min-w-40 rounded-lg border border-border bg-bg px-3 py-2 text-sm"
            maxLength={TEXT_MAX}
            placeholder={group.placeholder ?? ""}
            aria-describedby={hint}
            value={text}
            onChange={(event) =>
              update(setGroupText(answers, group, event.target.value))
            }
          />
          {group.text_kind === "time" && (
            <input
              type="time"
              aria-label={`${group.label}：选择时间`}
              aria-describedby={hint}
              className="rounded-lg border border-border bg-bg px-3 py-2 text-sm"
              value={/^\d{2}:\d{2}$/.test(text) ? text : ""}
              onChange={(event) =>
                update(setGroupText(answers, group, event.target.value))
              }
            />
          )}
          <span id={hint} className="small muted">
            选项和自己填写二选一，不填也可以。
          </span>
        </div>
      )}
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
  const joined = (group.shown ?? []).join("；");
  const original = joined.length <= 200 ? joined : "";
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
                          [fixed]: v === "no" ? [original] : undefined,
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
                placeholder="只修改需要更正的部分，其余安排请保留"
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
      groups.flatMap((g) => [
        ...(g.selected?.length ? [[g.key, g.selected]] : []),
        ...(g.text ? [[textKey(g.key), [g.text]]] : []),
      ]),
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
  const [note, setNote] = useState("");
  const submit = () => {
    const clean = cleanAnswers(answers);
    if (!validAnswers(card, clean)) return setNote("请至少选择一项再提交。");
    setNote("");
    confirm(clean);
  };
  return (
    <form
      aria-label={card.question}
      className="space-y-5 rounded-xl border border-border bg-bg-subtle p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!disabled) submit();
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
            answers={answers}
            disabled={disabled}
            update={setAnswers}
          />
        ),
      )}
      {answered ? (
        <p className="small muted">已确认</p>
      ) : stale ? (
        <p className="small muted">条件已变化，请按当前条件重新确认。</p>
      ) : (
        <>
          <Button type="submit" disabled={disabled}>
            确认并继续
          </Button>
          {(note || disabled) && (
            <p className="small muted">
              {note || "正在处理上一条消息，稍后即可提交。"}
            </p>
          )}
        </>
      )}
    </form>
  );
}

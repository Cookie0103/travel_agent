/** Collect related choices locally; one explicit confirmation submits the whole form. */
"use client";
import { useId, useState } from "react";
import type { Choice } from "@/lib/api";
import { choiceMessage, type DetailsAnswer } from "@/lib/choices";
import { Button } from "./ui/button";

const paceHelp: Record<string, string> = {
  慢节奏: "每天 2–3 个景点",
  标准: "每天约 4 个景点",
  特种兵: "每天 6–8 个景点",
};

export function TravelDetailsCard({
  card,
  disabled,
  stale,
  confirm,
}: {
  card: Choice;
  disabled: boolean;
  stale: boolean;
  confirm: (details: DetailsAnswer) => void;
}) {
  const shown = card.details!;
  const id = useId();
  const [transport, setTransport] = useState(shown.transport ?? "");
  const [pace, setPace] = useState(shown.pace ?? "");
  const [timesCorrect, setTimesCorrect] = useState<boolean | null>(null);
  const [corrections, setCorrections] = useState(shown.time_constraints);
  const answered = !!card.answered_option_id;
  const answer = {
    transport,
    pace,
    times_correct: timesCorrect,
    corrected_times:
      timesCorrect === false ? corrections.map((text) => text.trim()) : null,
  } as DetailsAnswer;
  let ready = false;
  try {
    choiceMessage(card, "confirm", answer);
    ready = true;
  } catch {
    /* 未填完仅禁用确认，不报错。 */
  }
  return (
    <form
      aria-label={card.question}
      className="space-y-5 rounded-xl border border-border bg-bg-subtle p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!disabled && ready) confirm(answer);
      }}
    >
      <p className="font-medium">{card.question}</p>
      <fieldset disabled={disabled} className="space-y-2">
        <legend className="mb-2 text-sm font-medium">交通</legend>
        <div className="flex flex-wrap gap-2">
          {shown.transport_options.map((option) => (
            <Button
              key={option.option_id}
              type="button"
              variant={transport === option.value ? "default" : "outline"}
              aria-pressed={transport === option.value}
              onClick={() => setTransport(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </fieldset>
      <fieldset disabled={disabled} className="space-y-2">
        <legend className="mb-2 text-sm font-medium">旅行节奏</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {shown.pace_options.map((option) => (
            <Button
              key={option.option_id}
              type="button"
              className="h-auto flex-col gap-1 whitespace-normal px-3 py-3"
              variant={pace === option.value ? "default" : "outline"}
              aria-pressed={pace === option.value}
              onClick={() => setPace(option.value)}
            >
              <span>{option.label}</span>
              <span className="text-xs font-normal">
                {paceHelp[option.value]}
              </span>
            </Button>
          ))}
        </div>
        <p className="small muted">首末日会按抵达、离开时间调整。</p>
      </fieldset>
      {!!shown.time_constraints.length && (
        <fieldset disabled={disabled} className="space-y-3">
          <legend className="mb-2 text-sm font-medium">
            抵达／离开时间对吗？
          </legend>
          {shown.time_constraints.map((text, index) => (
            <p className="text-sm whitespace-pre-wrap" key={index}>
              {text}
            </p>
          ))}
          {!answered && (
            <>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant={timesCorrect === true ? "default" : "outline"}
                  aria-pressed={timesCorrect === true}
                  onClick={() => setTimesCorrect(true)}
                >
                  是
                </Button>
                <Button
                  type="button"
                  variant={timesCorrect === false ? "default" : "outline"}
                  aria-pressed={timesCorrect === false}
                  onClick={() => setTimesCorrect(false)}
                >
                  不是
                </Button>
              </div>
              {timesCorrect === false && (
                <div className="space-y-2">
                  {corrections.map((correction, index) => (
                    <div className="space-y-2" key={index}>
                      <label
                        htmlFor={`${id}-times-${index}`}
                        className="text-sm"
                      >
                        请修改安排
                        {corrections.length > 1 ? ` ${index + 1}` : ""}
                        中的日期和时间
                      </label>
                      <textarea
                        id={`${id}-times-${index}`}
                        className="min-h-24 w-full rounded-lg border border-border bg-bg p-3 text-sm"
                        maxLength={200}
                        value={correction}
                        onChange={(event) =>
                          setCorrections((old) =>
                            old.map((text, i) =>
                              i === index ? event.target.value : text,
                            ),
                          )
                        }
                        required
                      />
                    </div>
                  ))}
                  <p className="small muted">
                    只修改需要更正的部分，其余安排请保留。
                  </p>
                </div>
              )}
            </>
          )}
        </fieldset>
      )}
      {answered ? (
        <p className="small muted">已确认出行安排</p>
      ) : stale ? (
        <p className="small muted">条件已变化，请按当前条件重新确认。</p>
      ) : (
        <>
          <Button type="submit" disabled={disabled || !ready}>
            确认并继续
          </Button>
          {!ready && (
            <p className="small muted">
              选好交通、旅行节奏
              {shown.time_constraints.length ? "，并确认时间" : ""}
              后一起提交；也可以在对话框里补充。
            </p>
          )}
        </>
      )}
    </form>
  );
}

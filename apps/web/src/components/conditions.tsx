/** Explicit conditions form; the server owns revisions and validation. */
"use client";
import { useState } from "react";
import type { RequestState } from "@/lib/api";
import { PACES } from "@/lib/pace";
import {
  conditionsForm,
  conditionPatch,
  type ConditionPatch,
} from "@/lib/condition-patch";

export function Conditions({
  request,
  disabled,
  save,
}: {
  request: RequestState;
  disabled: boolean;
  save: (patch: ConditionPatch) => Promise<boolean | undefined>;
}) {
  const [form, setForm] = useState(() => conditionsForm(request));
  const change = (key: keyof typeof form, value: string) =>
    setForm((old) => ({ ...old, [key]: value }));
  const [formError, setFormError] = useState("");
  return (
    <form
      className="conditions"
      onSubmit={(event) => {
        event.preventDefault();
        setFormError("");
        try {
          void save(conditionPatch(request, form));
        } catch (failure) {
          setFormError(
            failure instanceof Error ? failure.message : "条件输入无效。",
          );
        }
      }}
    >
      <div className="section-heading">
        <h2>编辑条件</h2>
        <span className="tag">版本 {request.revision}</span>
      </div>
      <label>
        目的地
        <input
          maxLength={40}
          value={form.city}
          placeholder="目的地待补充"
          onChange={(event) => change("city", event.target.value)}
        />
      </label>
      <label>
        开始日期
        <input
          type="date"
          value={form.start_date}
          onChange={(e) => change("start_date", e.target.value)}
        />
      </label>
      <label>
        结束日期
        <input
          type="date"
          min={form.start_date}
          value={form.end_date}
          onChange={(e) => change("end_date", e.target.value)}
        />
      </label>
      <div className="pair">
        <label>
          成人
          <input
            type="number"
            min="1"
            max="12"
            value={form.adults}
            onChange={(e) => change("adults", e.target.value)}
          />
        </label>
        <label>
          房间
          <input
            type="number"
            min="1"
            max="6"
            value={form.rooms}
            onChange={(e) => change("rooms", e.target.value)}
          />
        </label>
      </div>
      <label>
        儿童情况
        <select
          value={form.child_state}
          onChange={(e) => change("child_state", e.target.value)}
        >
          <option value="unknown">未填</option>
          <option value="none">无儿童</option>
          <option value="ages">有儿童</option>
        </select>
      </label>
      {form.child_state === "ages" && (
        <label>
          儿童年龄
          <input
            placeholder="填写年龄；婴儿填0，多名用逗号分开"
            value={form.child_ages}
            onChange={(e) => change("child_ages", e.target.value)}
          />
        </label>
      )}
      <label>
        全程预算（JPY）
        <input
          type="number"
          min="0.01"
          step="0.01"
          value={form.budget}
          onChange={(e) => change("budget", e.target.value)}
        />
      </label>
      <div className="pair">
        <label>
          交通
          <select
            value={form.transport}
            onChange={(e) => change("transport", e.target.value)}
          >
            <option value="">未知</option>
            <option value="walk">步行</option>
            <option value="transit">公共交通</option>
            <option value="taxi">出租车</option>
          </select>
        </label>
        <label>
          每日出发
          <input
            type="time"
            step="any"
            value={form.departure_time}
            onChange={(e) => change("departure_time", e.target.value)}
          />
        </label>
      </div>
      <label>
        节奏
        <select
          value={form.pace}
          onChange={(e) => change("pace", e.target.value)}
        >
          <option value="">未知</option>
          {PACES.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
      {formError && (
        <p role="alert" className="error">
          {formError}
        </p>
      )}
      <button disabled={disabled} className="primary">
        保存条件
      </button>
      <p className="muted small">
        修改条件会使旧报价和草稿不再适用；未知信息会显示警告。
      </p>
    </form>
  );
}

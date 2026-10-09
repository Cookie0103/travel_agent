/** Explicit conditions form; the server owns revisions and validation. */
"use client";
import { Button } from "./ui/button";
import { useState, type MouseEvent } from "react";
import type { RequestState } from "@/lib/api";
import { PACES } from "@/lib/pace";
import { sourceLabel } from "@/lib/condition-source";
import {
  conditionsForm,
  conditionPatch,
  type ConditionPatch,
} from "@/lib/condition-patch";

function openDatePicker(event: MouseEvent<HTMLLabelElement>) {
  const input =
    event.currentTarget.querySelector<HTMLInputElement>('input[type="date"]');
  if (!input || typeof input.showPicker !== "function") return;
  try {
    input.focus();
    input.showPicker();
    event.preventDefault();
  } catch {
    // Unsupported or restricted browsers retain the native icon and keyboard input.
  }
}

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
  const source = (field: string) => (
    <span className="small muted" aria-hidden="true">
      {sourceLabel(request.field_sources, field)}
    </span>
  );
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
        {source("city")}
        <input
          maxLength={40}
          value={form.city}
          placeholder="目的地待补充"
          onChange={(event) => change("city", event.target.value)}
        />
      </label>
      <label onClick={openDatePicker}>
        开始日期
        {source("start_date")}
        <input
          type="date"
          value={form.start_date}
          onChange={(e) => change("start_date", e.target.value)}
        />
      </label>
      <label onClick={openDatePicker}>
        结束日期
        {source("end_date")}
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
          {source("adults")}
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
          {source("rooms")}
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
        {source("child_ages")}
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
        {source("budget")}
        <input
          type="number"
          min="0.01"
          step="0.01"
          value={form.budget}
          onChange={(e) => change("budget", e.target.value)}
        />
      </label>
      {Object.hasOwn(request, "lodging_budget") && request.budget_relation ? (
        <>
          <label>
            住宿预算口径
            {source("lodging_budget")}
            <select
              value={form.lodging_basis}
              onChange={(e) =>
                setForm((old) => ({
                  ...old,
                  lodging_basis: e.target.value,
                  lodging_currency:
                    old.lodging_currency ||
                    (e.target.value ? request.currency : ""),
                }))
              }
            >
              <option value="">未填</option>
              <option value="per_room_night">每房每晚</option>
              <option value="total">住宿总额</option>
            </select>
          </label>
          {form.lodging_basis && (
            <>
              <div className="pair">
                <label>
                  住宿预算下限
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={form.lodging_lower}
                    onChange={(e) => change("lodging_lower", e.target.value)}
                  />
                </label>
                <label>
                  住宿预算上限
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={form.lodging_upper}
                    onChange={(e) => change("lodging_upper", e.target.value)}
                  />
                </label>
              </div>
              <label>
                住宿预算币种
                <input
                  maxLength={3}
                  pattern="[A-Z]{3}"
                  value={form.lodging_currency}
                  onChange={(e) =>
                    change("lodging_currency", e.target.value.toUpperCase())
                  }
                />
              </label>
              <p className="muted small">
                单值填相同上下限；仅限额填上限。住宿预算是全程预算的分项，两个原值都会保存。
              </p>
            </>
          )}
        </>
      ) : (
        <p className="warning">
          服务版本暂不支持住宿预算；此分项无法保存或校验。
        </p>
      )}
      <div className="pair">
        <label>
          交通
          {source("transport")}
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
          {source("departure_time")}
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
        {source("soft_constraints")}
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
      <Button disabled={disabled} className="primary">
        保存条件
      </Button>
      <p className="muted small">
        修改条件会使旧报价和草稿不再适用；未知信息会显示警告。
      </p>
    </form>
  );
}

/** Explicit conditions form; the server owns revisions and validation. */
"use client";
import { useState } from "react";
import type { components } from "@/lib/api-types";
import type { RequestState } from "@/lib/api";

export function Conditions({
  request,
  disabled,
  save,
}: {
  request: RequestState;
  disabled: boolean;
  save: (
    value: Partial<components["schemas"]["TravelConditions"]>,
  ) => Promise<boolean | undefined>;
}) {
  const [start, setStart] = useState(request.start_date || "2026-11-03");
  const [city, setCity] = useState(request.city || "京都");
  const [end, setEnd] = useState(request.end_date || "2026-11-05");
  const [adults, setAdults] = useState(request.adults || 2);
  const [children, setChildren] = useState(
    (request.child_ages || []).join(","),
  );
  const [rooms, setRooms] = useState(request.rooms || 1);
  const [budget, setBudget] = useState(request.budget || "50000");
  const [transport, setTransport] = useState<"walk" | "transit" | "taxi">(
    request.transport || "walk",
  );
  const [departure, setDeparture] = useState(request.departure_time || "09:00");
  const [formError, setFormError] = useState("");
  return (
    <form
      className="conditions"
      onSubmit={(event) => {
        event.preventDefault();
        setFormError("");
        const ages = children.trim()
          ? children.split(/[,，]/).map((age) => Number(age.trim()))
          : [];
        if (
          ages.some((age) => !Number.isInteger(age) || age < 0 || age > 17) ||
          (children.trim() &&
            children.split(/[,，]/).some((age) => !age.trim()))
        ) {
          setFormError("儿童年龄请填 0–17 的整数，用逗号分开。");
          return;
        }
        void save({
          city,
          start_date: start,
          end_date: end,
          adults,
          child_ages: ages,
          rooms,
          budget: String(budget),
          currency: "JPY",
          transport,
          departure_time: departure,
        });
      }}
    >
      <div className="section-heading">
        <h2>编辑条件</h2>
        <span className="tag">版本 {request.revision}</span>
      </div>
      <label>
        目的地
        <input
          required
          maxLength={40}
          value={city}
          placeholder="例如 大阪、札幌、那霸、箱根"
          onChange={(event) => setCity(event.target.value)}
        />
      </label>
      <label>
        开始日期
        <input
          type="date"
          required
          value={start}
          onChange={(e) => setStart(e.target.value)}
        />
      </label>
      <label>
        结束日期
        <input
          type="date"
          required
          min={start}
          value={end}
          onChange={(e) => setEnd(e.target.value)}
        />
      </label>
      <div className="pair">
        <label>
          成人
          <input
            type="number"
            min="1"
            max="12"
            required
            value={adults}
            onChange={(e) => setAdults(Number(e.target.value))}
          />
        </label>
        <label>
          房间
          <input
            type="number"
            min="1"
            max="6"
            required
            value={rooms}
            onChange={(e) => setRooms(Number(e.target.value))}
          />
        </label>
      </div>
      <label>
        儿童年龄
        <input
          placeholder="例如 6, 10；无儿童留空"
          value={children}
          onChange={(e) => setChildren(e.target.value)}
        />
      </label>
      <label>
        全程预算（JPY）
        <input
          type="number"
          min="1"
          step="0.01"
          required
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
        />
      </label>
      <div className="pair">
        <label>
          交通
          <select
            value={transport}
            onChange={(e) => setTransport(e.target.value as typeof transport)}
          >
            <option value="walk">步行</option>
            <option value="transit">公共交通</option>
            <option value="taxi">出租车</option>
          </select>
        </label>
        <label>
          每日出发
          <input
            type="time"
            required
            value={departure}
            onChange={(e) => setDeparture(e.target.value)}
          />
        </label>
      </div>
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

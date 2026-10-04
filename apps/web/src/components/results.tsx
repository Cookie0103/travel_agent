/** Render canonical business cards; money, provenance and conflicts come from the server. */
"use client";
import { useEffect, useState } from "react";
import { planUnavailable, expiredHotels, partyLabel } from "@/lib/availability";
import { sourceHref, type Hotels, type Plan } from "@/lib/api";
import type { components } from "@/lib/api-types";
const date = (value: string) =>
  new Date(value).toLocaleString("zh-CN", {
    timeZone: "Asia/Tokyo",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

const dayFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Tokyo",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** Group plan cards by Asia/Tokyo calendar day; `index` stays the global 0-based position. */
export function planDays(plan: Plan) {
  const days: {
    day: string;
    items: { item: Plan["cards"][number]; index: number }[];
  }[] = [];
  plan.cards.forEach((item, index) => {
    const day = dayFormat.format(new Date(item.start));
    const last = days.at(-1);
    if (last?.day === day) last.items.push({ item, index });
    else days.push({ day, items: [{ item, index }] });
  });
  return days;
}

export function useClock() {
  const [now, setNow] = useState(0);
  useEffect(() => {
    const update = () => setNow(Date.now());
    update();
    const timer = setInterval(update, 10_000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

/** Guide/source references link out only when they are valid HTTPS URLs. */
export function SourceRef({ value }: { value: string | null }) {
  const href = value ? sourceHref(value) : undefined;
  return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {value}
    </a>
  ) : (
    <>{value ?? "未知"}</>
  );
}

function Hotel({ card }: { card: components["schemas"]["UiHotelCard"] }) {
  return (
    <article className="hotel-card">
      <span className="tag">模拟报价</span>
      <h3>{card.hotel_name}</h3>
      <p>{card.room_type}</p>
      <p className="small">
        {String(card.stay.start_date)} — {String(card.stay.end_date)} ·{" "}
        {partyLabel(card.stay)}
      </p>
      <strong className="price">
        {card.total === null ? "总价未知" : `¥ ${card.total}`}
      </strong>
      <p className="small">
        基础 {card.base_amount} · 税 {card.tax_amount ?? "未知"} · 费{" "}
        {card.fee_amount ?? "未知"}
      </p>
      <p>
        {card.breakfast ? "含早餐" : "不含早餐"} ·{" "}
        {card.refundable ? "可退" : "不可退"}
      </p>
      <details>
        <summary>来源与版本</summary>
        <p className="muted small">
          有效至 {date(card.expires_at)}
          <br />
          来源：
          <SourceRef value={card.source_ref} />
          <br />
          报价条件版本 {card.request_revision}
          <br />
          来源版本 {card.content_version?.slice(0, 12) || "未知"}
        </p>
      </details>
      {card.lodging_exceeds_trip_budget && (
        <p className="error">住宿已超过全程预算</p>
      )}
    </article>
  );
}
export function HotelResults({
  hotels,
  disabled,
  revision,
  hold,
  compact = false,
}: {
  compact?: boolean;
  hotels: Hotels;
  disabled: boolean;
  revision?: number;
  hold: (offerId: string, revision: number) => Promise<void>;
}) {
  const expired = expiredHotels(hotels, useClock());
  return (
    <section className={`results-section${compact ? " is-compact" : ""}`}>
      <div className="section-heading">
        <h2>酒店比较</h2>
      </div>
      <p className="muted">{hotels.comparison.scope}</p>
      {expired && (
        <p className="warning">
          报价已过期，当前最低价结论不可用；请重新比较酒店。
        </p>
      )}
      {!hotels.comparison.comparable && (
        <p className="warning">
          无法判定最低总价：{hotels.comparison.reasons.join("；")}
        </p>
      )}
      <div className="hotel-grid">
        {hotels.cards.map((card) => (
          <div key={card.offer_id}>
            <Hotel card={card} />
            <button
              disabled={
                disabled ||
                expired ||
                card.total === null ||
                revision !== card.request_revision
              }
              onClick={() => void hold(card.offer_id, card.request_revision)}
            >
              暂留模拟房间
            </button>
            {!expired &&
              hotels.comparison.lowest_offer_ids.includes(card.offer_id) && (
                <p className="lowest">所列同口径报价中的最低价</p>
              )}
          </div>
        ))}
      </div>
    </section>
  );
}
export function PlanResults({
  plan,
  disabled,
  confirm,
  lock,
}: {
  plan: Plan;
  disabled: boolean;
  confirm?: () => Promise<void>;
  lock?: (id: string) => Promise<void>;
}) {
  const stale = planUnavailable(plan, useClock());
  const blocked = stale || plan.validation.status === "conflict";
  return (
    <section className="results-section">
      <div className="section-heading">
        <h2>{plan.draft_id ? "待确认行程" : `正式行程 · V${plan.version}`}</h2>
        <span className="tag">条件版本 {plan.request_revision}</span>
      </div>
      <p className={`status-bar status-bar-${plan.validation.status}`}>
        {plan.validation.status === "conflict"
          ? "有硬冲突，不能确认"
          : plan.validation.status === "partial"
            ? "部分可校验；仍有未知项"
            : "已通过当前范围校验"}{" "}
        · 已知 {plan.validation.known_cost} / 估算{" "}
        {plan.validation.estimated_cost} JPY
      </p>
      {stale && (
        <p role="alert" className="error">
          草稿或引用已失效：请读取当前条件并重新生成；不会覆盖正式版本。
        </p>
      )}
      <ul className="checks">
        {plan.validation.checks
          .filter((check) => check.status !== "verified")
          .map((check, index) => (
            <li key={index}>
              {check.status === "conflict" ? "冲突" : "未知"}：{check.message}
            </li>
          ))}
      </ul>
      {plan.validation.truncated && (
        <p className="muted small">
          展示优先级最高的 12 项；完整校验仍由服务端执行。
        </p>
      )}
      <p className="muted small">{plan.validation.scope}</p>
      {plan.base_version !== undefined && plan.base_version !== null && (
        <p className="base-version">
          基于正式版本 V{plan.base_version} · {plan.changes?.length || 0} 项变化
          · 酒店{plan.hotel_changed ? "有变化" : "保留"}
        </p>
      )}
      {!!plan.changes?.length && (
        <details>
          <summary>查看本次差异</summary>
          {plan.changes.map((change) => (
            <p key={change.item_id} className="small">
              {change.op === "update"
                ? "修改"
                : change.op === "add"
                  ? "新增"
                  : "移除"}
              ：
              {plan.cards.find((card) => card.item_id === change.item_id)
                ?.name ?? "已移除项目"}{" "}
              <span className="tabular">
                {change.before ? date(change.before.start) : "无"} →{" "}
                {change.after ? date(change.after.start) : "无"}
              </span>
            </p>
          ))}
        </details>
      )}
      <div className="itinerary">
        {planDays(plan).map(({ day, items }, dayIndex) => (
          <div key={day} className="day">
            <h3 className="day-heading">
              Day {dayIndex + 1}{" "}
              <span className="muted small">{day.slice(5)}</span>
            </h3>
            {items.map(({ item, index }) => (
              <article key={item.item_id} className="visit">
                <span className="visit-number">{index + 1}</span>
                <div>
                  <h3>{item.name}</h3>
                  <p className="tabular">
                    {date(item.start)} — {date(item.end)}
                  </p>
                  <p className="muted small">
                    历史快照 · <SourceRef value={item.source_ref} />
                  </p>
                </div>
                {!plan.draft_id && lock && (
                  <button
                    disabled={disabled}
                    onClick={() => void lock(item.item_id)}
                    aria-label={`${item.locked ? "解锁" : "锁定"}第${index + 1}项`}
                  >
                    {item.locked ? "已锁定" : "锁定"}
                  </button>
                )}
              </article>
            ))}
          </div>
        ))}
      </div>
      {plan.hotel && (
        <details>
          <summary>住宿报价</summary>
          <Hotel card={plan.hotel} />
        </details>
      )}
      {plan.draft_id && confirm && (
        <div className="confirm-bar">
          <p>确认只保存此草稿；unknown 保留，不创建订单或付款。</p>
          <button
            className="primary"
            disabled={disabled || blocked || plan.status === "confirmed"}
            onClick={() => void confirm()}
          >
            确认保存此版本
          </button>
        </div>
      )}
      <p className="muted small">{plan.guidance}</p>
    </section>
  );
}

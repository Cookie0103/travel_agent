/** Render canonical business cards; money, provenance and conflicts come from the server. */
"use client";
import { useEffect, useState } from "react";
import {
  planUnavailable,
  planRefreshNotice,
  hotelQuoteNeedsRefresh,
  expiredHotels,
  partyLabel,
} from "@/lib/availability";
import { sourceHref, type Hotels, type Plan } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { hotelGroups, selectedHotelOffer } from "@/lib/hotel-groups";
import { hotelLinks } from "@/lib/hotel-links";
import { CalendarButton } from "./calendar-button";
export const formatYen = (value: string) =>
  Number(value).toLocaleString("ja-JP");
const rakutenCredit = `<!-- Rakuten Web Services Attribution Snippet FROM HERE -->
<a href="https://developers.rakuten.com/" target="_blank">Supported by Rakuten Developers</a>
<!-- Rakuten Web Services Attribution Snippet TO HERE -->`;
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
  const links = hotelLinks(card);
  return (
    <article className="hotel-card">
      {/* 楽天图片按供应商原URL展示；避免图片代理和公共缓存。 */}
      {card.image_url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          className="hotel-image"
          src={card.image_url}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
        />
      )}
      <span className="tag">
        {card.data_mode === "live" ? "乐天实时" : "模拟报价"}
      </span>
      <h3>{card.hotel_name}</h3>
      <p>{card.room_type}</p>
      {card.review_average != null && <p>★ {card.review_average}</p>}
      <p className="small">
        {String(card.stay.start_date)} — {String(card.stay.end_date)} ·{" "}
        {partyLabel(card.stay)}
      </p>
      <strong className="price">
        {card.total === null ? "总价未知" : `¥ ${formatYen(card.total)}`}
      </strong>
      <p className="small">
        {card.data_mode === "live" ? (
          "含税和服务费，明细未知"
        ) : (
          <>
            基础 {formatYen(card.base_amount)} · 税 {card.tax_amount ?? "未知"}{" "}
            · 费 {card.fee_amount ?? "未知"}
          </>
        )}
      </p>
      {card.total_reason && (
        <p className="warning small">{card.total_reason}</p>
      )}
      <p>
        {card.breakfast === null
          ? "早餐未知"
          : card.breakfast
            ? "含早餐"
            : "不含早餐"}{" "}
        ·{" "}
        {card.refundable === null
          ? "退款规则请以乐天为准"
          : card.refundable
            ? "可退"
            : "不可退"}
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
      {card.lodging_exceeds_lodging_budget === true && (
        <p className="warning">报价超过住宿预算上限</p>
      )}
      {card.lodging_exceeds_lodging_budget === null && (
        <p className="muted small">
          住宿预算上限、数量或币种未齐，无法判断此分项。
        </p>
      )}
      {card.lodging_exceeds_trip_budget && (
        <p className="error">住宿已超过全程预算</p>
      )}
      {card.data_mode === "live" && (
        <>
          {links.info ? (
            <a
              className="button-link primary"
              href={links.info}
              target="_blank"
              rel="noopener noreferrer"
            >
              查看酒店 ↗
            </a>
          ) : (
            <p className="small">酒店介绍链接未知</p>
          )}
          {links.plans && (
            <a
              className="button-link"
              href={links.plans}
              target="_blank"
              rel="noopener noreferrer"
            >
              套餐列表 ↗
            </a>
          )}
          {links.reservation && (
            <a
              className="button-link"
              href={links.reservation}
              target="_blank"
              rel="noopener noreferrer"
            >
              预订页面 ↗
            </a>
          )}
          {links.legacy && (
            <a
              className="button-link"
              href={links.legacy}
              target="_blank"
              rel="noopener noreferrer"
            >
              旧报价链接 ↗
            </a>
          )}
        </>
      )}
    </article>
  );
}
export function HotelResults({
  hotels,
  disabled,
  revision,
  hold,
  choose,
  compact = false,
}: {
  compact?: boolean;
  choose?: (card: components["schemas"]["UiHotelCard"]) => void;
  hotels: Hotels;
  disabled: boolean;
  revision?: number;
  hold: (offerId: string, revision: number) => Promise<void>;
}) {
  const now = useClock();
  const expired = expiredHotels(hotels, now);
  const groups = hotelGroups(hotels.cards);
  return (
    <section className={`results-section${compact ? " is-compact" : ""}`}>
      <div className="section-heading">
        <h2>酒店比较 · {groups.length}家</h2>
      </div>
      <p className="muted">{hotels.comparison.scope}</p>
      {hotels.comparison.budget_relation && (
        <p className="warning">{hotels.comparison.budget_relation.message}</p>
      )}
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
        {groups.map((group) => (
          <HotelPackage
            key={group.hotel_id}
            offers={group.offers}
            disabled={disabled}
            revision={revision}
            hold={hold}
            choose={choose}
            expiredComparison={expired}
            lowest={hotels.comparison.lowest_offer_ids}
          />
        ))}
      </div>
      {hotels.cards.some((card) => card.data_mode === "live") && (
        <div
          className="small muted"
          dangerouslySetInnerHTML={{ __html: rakutenCredit }}
        />
      )}
    </section>
  );
}
function HotelPackage({
  offers,
  disabled,
  revision,
  hold,
  choose,
  lowest,
  expiredComparison,
}: {
  offers: Hotels["cards"];
  disabled: boolean;
  revision?: number;
  hold: (offerId: string, revision: number) => Promise<void>;
  choose?: (card: Hotels["cards"][number]) => void;
  lowest: string[];
  expiredComparison: boolean;
}) {
  const [selected, setSelected] = useState<string>();
  const card = selectedHotelOffer(offers, selected);
  const now = useClock();
  if (!card) return null;
  const expired = now > 0 && Date.parse(card.expires_at) <= now;
  return (
    <div>
      {offers.length > 1 && (
        <label>
          房型/套餐
          <select
            aria-label={`${card.hotel_name}的房型/套餐`}
            value={card.offer_id}
            onChange={(event) => setSelected(event.target.value)}
          >
            {offers.map((offer, index) => (
              <option key={offer.offer_id} value={offer.offer_id}>
                {index + 1}. {offer.room_type} ·{" "}
                {offer.total === null
                  ? "总价未知"
                  : `¥ ${formatYen(offer.total)}`}
              </option>
            ))}
          </select>
        </label>
      )}
      <Hotel card={card} />
      {expired && (
        <p className="warning">所选套餐报价已过期，请重新比较酒店。</p>
      )}
      {card.data_mode === "live" ? (
        <>
          {choose && (
            <button
              disabled={
                disabled || expired || revision !== card.request_revision
              }
              onClick={() => choose(card)}
            >
              选用此酒店
            </button>
          )}
        </>
      ) : (
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
      )}
      {!expiredComparison && lowest.includes(card.offer_id) && (
        <p className="lowest">所列同口径报价中的最低价</p>
      )}
    </div>
  );
}

export function PlanResults({
  plan,
  disabled,
  confirm,
  lock,
  token,
}: {
  plan: Plan;
  disabled: boolean;
  confirm?: () => Promise<void>;
  lock?: (id: string) => Promise<void>;
  token?: string;
}) {
  const now = useClock();
  const stale = planUnavailable(plan, now);
  const refreshNotice = planRefreshNotice(plan, now);
  const blocked = stale || plan.validation.status === "conflict";
  return (
    <section className="results-section">
      <div className="section-heading">
        <h2>{plan.draft_id ? "待确认行程" : `正式行程 · V${plan.version}`}</h2>
        <span className="tag">条件版本 {plan.request_revision}</span>
      </div>
      {!plan.draft_id && token && (
        <CalendarButton
          planId={plan.plan_id}
          token={token}
          disabled={disabled}
        />
      )}
      <p className={`status-bar status-bar-${plan.validation.status}`}>
        {plan.validation.status === "conflict"
          ? "有硬冲突，不能确认"
          : plan.validation.status === "partial"
            ? "部分可校验；仍有未知项"
            : "已通过当前范围校验"}{" "}
        · 已知 {plan.validation.known_cost} / 估算{" "}
        {plan.validation.estimated_cost} JPY
      </p>
      {refreshNotice && (
        <p role="alert" className={plan.draft_id ? "error" : "warning"}>
          {refreshNotice}
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
                  <h3>
                    {sourceHref(item.source_ref ?? "") ? (
                      <a
                        href={sourceHref(item.source_ref ?? "")}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {item.name}
                      </a>
                    ) : (
                      item.name
                    )}
                  </h3>
                  <p className="tabular">
                    {date(item.start)} — {date(item.end)}
                  </p>
                  {plan.needs_refresh.includes(item.place_evidence_id) && (
                    <p className="warning small">
                      此景点参考信息需更新，使用前请重新查询。
                    </p>
                  )}
                  {item.route_evidence_id &&
                    plan.needs_refresh.includes(item.route_evidence_id) && (
                      <p className="warning small">
                        到此景点的路线信息需更新，使用前请重新查询。
                      </p>
                    )}
                  {item.note && <p className="muted small">{item.note}</p>}
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
            {plan.hotel && dayIndex < planDays(plan).length - 1 && (
              <p className="muted small">住宿：{plan.hotel.hotel_name}</p>
            )}
          </div>
        ))}
      </div>
      {plan.hotel && (
        <details>
          <summary>
            住宿报价{hotelQuoteNeedsRefresh(plan, now) ? " · 需更新" : ""}
          </summary>
          {hotelQuoteNeedsRefresh(plan, now) && (
            <p className="warning small">
              此住宿报价需更新，价格与可订状态请重新查询。
            </p>
          )}
          <Hotel card={plan.hotel} />
        </details>
      )}
      {plan.draft_id && confirm && (
        <div className="confirm-bar">
          <button
            className="primary"
            disabled={disabled || blocked || plan.status === "confirmed"}
            onClick={() => void confirm()}
          >
            确认保存此版本
          </button>
        </div>
      )}
    </section>
  );
}

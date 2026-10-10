/** Render canonical business cards; money, provenance and conflicts come from the server. */
"use client";
import { Button } from "./ui/button";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
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
import { moreTile, scrollButtons } from "@/lib/hotel-more";
import { validationGroups, checkTargets } from "@/lib/validation-groups";
import { CalendarButton } from "./calendar-button";
export const formatYen = (value: string) =>
  Number(value).toLocaleString("ja-JP");
const rakutenCredit = `<!-- Rakuten Web Services Attribution Snippet FROM HERE -->
<a href="https://developers.rakuten.com/" target="_blank">Supported by Rakuten Developers</a>
<!-- Rakuten Web Services Attribution Snippet TO HERE -->`;
export { planDays } from "@/lib/itinerary";
import {
  planDays,
  daySections,
  cleanNote,
  itineraryTime as date,
} from "@/lib/itinerary";

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

function Hotel({
  card,
  picker,
  children,
}: {
  card: components["schemas"]["UiHotelCard"];
  picker?: ReactNode;
  children?: ReactNode;
}) {
  const links = hotelLinks(card);
  const review =
    card.review_average != null || card.review_count != null
      ? [
          card.review_average != null ? `★ ${card.review_average}` : null,
          card.review_count != null ? `${card.review_count}条评价` : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : null;
  return (
    <article className="hotel-card">
      {/* 楽天图片按供应商原URL展示；避免图片代理和公共缓存。 */}
      {card.image_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          className="hotel-image"
          src={card.image_url}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
        />
      ) : (
        <div className="hotel-image hotel-image-empty" aria-hidden="true" />
      )}
      <div className="hotel-top">
        <span className="tag">
          {card.data_mode === "live" ? "乐天实时" : "模拟报价"}
        </span>
        <h3 title={card.hotel_name}>{card.hotel_name}</h3>
        {review && <p className="small">{review}</p>}
        {card.address && <p className="small">{card.address}</p>}
        {picker}
        <p>{card.room_type}</p>
        {!!card.room_tags?.length && (
          <p className="muted small">{card.room_tags.join(" · ")}</p>
        )}
        {card.qualification_unknown && (
          <p className="warning">
            房型资格未知，请先核实限制；不能据此判断适合。
          </p>
        )}
        {card.room_preference_mismatch && (
          <p className="warning">此房型为宿舍或舱房，不符合独立房间偏好。</p>
        )}
        <p className="small">
          {String(card.stay.start_date)} — {String(card.stay.end_date)} ·{" "}
          {partyLabel(card.stay)}
        </p>
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
      </div>
      <div className="hotel-bottom">
        <strong className="price">
          {card.total === null ? "总价未知" : `¥ ${formatYen(card.total)}`}
        </strong>
        {card.price_basis && (
          <p className="muted small hotel-basis">{card.price_basis}</p>
        )}
        <p className="small">
          {card.data_mode === "live" ? (
            "含税和服务费，明细未知"
          ) : (
            <>
              基础 {formatYen(card.base_amount)} · 税{" "}
              {card.tax_amount ?? "未知"} · 费 {card.fee_amount ?? "未知"}
            </>
          )}
        </p>
        {card.total_reason && (
          <p className="warning small">{card.total_reason}</p>
        )}
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
      </div>
      <div className="hotel-actions">
        {card.data_mode === "live" && (
          <div className="hotel-links">
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
          </div>
        )}
        {children}
      </div>
    </article>
  );
}

/** Horizontal strip of equal-height cards; native scrolling plus prev/next buttons. */
function HotelStrip({
  label,
  watch,
  children,
}: {
  label: string;
  watch: string;
  children: ReactNode;
}) {
  const regionId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const [state, setState] = useState({
    overflow: false,
    canPrev: false,
    canNext: false,
  });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () =>
      setState((prev) => {
        const next = scrollButtons(
          el.scrollLeft,
          el.clientWidth,
          el.scrollWidth,
        );
        return next.overflow === prev.overflow &&
          next.canPrev === prev.canPrev &&
          next.canNext === prev.canNext
          ? prev
          : next;
      });
    update();
    el.addEventListener("scroll", update, { passive: true });
    const observer =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(update);
    observer?.observe(el);
    for (const child of Array.from(el.children)) observer?.observe(child);
    return () => {
      el.removeEventListener("scroll", update);
      observer?.disconnect();
    };
  }, [watch]);
  const page = (direction: -1 | 1) =>
    ref.current?.scrollBy({
      left: direction * Math.max(ref.current.clientWidth * 0.8, 200),
      behavior: "auto",
    });
  return (
    <div className="hotel-strip-wrap">
      {state.overflow && (
        <div className="hotel-strip-nav">
          <Button
            variant="outline"
            type="button"
            aria-label="上一批酒店"
            aria-controls={regionId}
            disabled={!state.canPrev}
            onClick={() => page(-1)}
          >
            ←
          </Button>
          <Button
            variant="outline"
            type="button"
            aria-label="下一批酒店"
            aria-controls={regionId}
            disabled={!state.canNext}
            onClick={() => page(1)}
          >
            →
          </Button>
        </div>
      )}
      <div
        id={regionId}
        ref={ref}
        className="hotel-strip"
        tabIndex={0}
        role="region"
        aria-label={label}
      >
        {children}
      </div>
    </div>
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
  const more = moreTile(hotels);
  return (
    <section className={`results-section${compact ? " is-compact" : ""}`}>
      <div className="section-heading">
        <h2>酒店比较 · {groups.length}家</h2>
      </div>
      <p className="muted">{hotels.comparison.scope}</p>
      {hotels.comparison.room_preferences_question && (
        <p className="warning">{hotels.comparison.room_preferences_question}</p>
      )}
      {groups.length === 0 && <p>当前没有可展示的酒店报价。</p>}
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
          {groups.length === 0 ? "查询说明：" : "无法判定最低总价："}
          {hotels.comparison.reasons.join("；")}
        </p>
      )}
      <HotelStrip
        label={`酒店列表，共${groups.length}家，可左右滚动`}
        watch={`${hotels.cards.length}:${groups.length}:${more ? 1 : 0}`}
      >
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
        {more && (
          <a
            className="hotel-card hotel-more"
            href={more.href}
            target="_blank"
            rel="noopener noreferrer"
          >
            <strong>{more.title} ↗</strong>
            <span className="muted small">{more.note}</span>
          </a>
        )}
      </HotelStrip>
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
    <Hotel
      card={card}
      picker={
        offers.length > 1 ? (
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
        ) : undefined
      }
    >
      {expired && (
        <p className="warning">所选套餐报价已过期，请重新比较酒店。</p>
      )}
      {card.data_mode === "live" ? (
        <>
          {choose && (
            <Button
              variant="outline"
              disabled={
                disabled || expired || revision !== card.request_revision
              }
              onClick={() => choose(card)}
            >
              选用此酒店
            </Button>
          )}
        </>
      ) : (
        <Button
          variant="outline"
          disabled={
            disabled ||
            expired ||
            card.total === null ||
            revision !== card.request_revision
          }
          onClick={() => void hold(card.offer_id, card.request_revision)}
        >
          暂留模拟房间
        </Button>
      )}
      {!expiredComparison && lowest.includes(card.offer_id) && (
        <p className="lowest">所列同口径报价中的最低价</p>
      )}
    </Hotel>
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
  const checkPrefix = useId();
  const groups = validationGroups(plan.validation.checks);
  const days = planDays(plan);
  return (
    <section className="results-section">
      <div className="section-heading">
        <h2>{plan.draft_id ? "待确认行程" : `正式行程 · V${plan.version}`}</h2>
        <span className="tag">条件版本 {plan.request_revision}</span>
      </div>
      <p className="muted small">行程简介由 AI 整理，游玩时间为建议安排。</p>
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
      {!!groups.length && (
        <div className="checks">
          <p className="small">
            校验提醒 · 冲突 {plan.validation.check_counts.conflict ?? 0} · 未知{" "}
            {plan.validation.check_counts.unknown ?? 0}
          </p>
          {plan.validation.truncated && (
            <p className="muted small">
              下列分类计数仅含当前明细；其余校验未展开，上方为完整总数。
            </p>
          )}
          {groups.map((group, index) => (
            <details key={index}>
              <summary>
                {group.status === "conflict" ? "冲突" : "未知"} · {group.label}{" "}
                · {group.checks.length}条
              </summary>
              <ul>
                {group.checks.map((check, position) => (
                  <li key={position}>
                    {check.message}{" "}
                    {checkTargets(check.subject, plan.cards).map((target) => (
                      <a key={target} href={`#${checkPrefix}-item-${target}`}>
                        第{target + 1}项：{plan.cards[target].name}{" "}
                      </a>
                    ))}
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </div>
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
      <div className="mt-6 space-y-6">
        {days.map(({ day, items, cities, stays, transfer }, dayIndex) => (
          <section
            key={`${day}-${dayIndex}`}
            aria-label={`第${dayIndex + 1}天`}
          >
            <h3 className="mb-4 text-xl font-semibold">
              第 {dayIndex + 1} 天{" "}
              <span className="ml-2 text-sm text-text-muted">
                {day === "时间待定" ? day : day.slice(5)}
              </span>
            </h3>
            {!!cities.length && (
              <p className="mb-2 font-semibold">{cities.join(" → ")}</p>
            )}
            {transfer && (
              <p className="mb-3 text-sm text-text-muted">
                转场建议（未查询车次与票价）：当天预留转场时间，具体路线与耗时需另行确认。
              </p>
            )}
            <div className="ml-2 border-l border-border pl-5">
              {daySections(items).map((section, sectionIndex) => (
                <section key={sectionIndex} className="relative mb-4">
                  <span
                    className="absolute -left-[26px] top-2 size-3 rounded-full bg-primary"
                    aria-hidden="true"
                  />
                  <h4 className="mb-2 text-base font-semibold">
                    {section.label}
                  </h4>
                  <div className="rounded-xl border border-border bg-bg">
                    {section.items.map(({ item, index }) => (
                      <article
                        key={item.item_id}
                        className="flex scroll-mt-4 items-start gap-3 border-b border-border p-4 last:border-0"
                        id={`${checkPrefix}-item-${index}`}
                        tabIndex={-1}
                      >
                        <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-bg-subtle text-sm text-text-muted">
                          {index + 1}
                        </span>
                        <div className="min-w-0 flex-1">
                          <h3 className="text-base font-semibold">
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
                          {plan.needs_refresh.includes(
                            item.place_evidence_id,
                          ) && (
                            <p className="warning small">
                              此景点参考信息需更新，使用前请重新查询。
                            </p>
                          )}
                          {item.route_evidence_id &&
                            plan.needs_refresh.includes(
                              item.route_evidence_id,
                            ) && (
                              <p className="warning small">
                                到此景点的路线信息需更新，使用前请重新查询。
                              </p>
                            )}
                          {item.note && cleanNote(item.note) && (
                            <p className="muted small">
                              {cleanNote(item.note)}
                            </p>
                          )}
                        </div>
                        {!plan.draft_id && lock && (
                          <Button
                            variant="outline"
                            disabled={disabled}
                            onClick={() => void lock(item.item_id)}
                            aria-label={`${item.locked ? "解锁" : "锁定"}第${index + 1}项`}
                          >
                            {item.locked ? "已锁定" : "锁定"}
                          </Button>
                        )}
                      </article>
                    ))}
                  </div>
                </section>
              ))}
              {stays.map((stay) => (
                <section className="relative" key={stay.hotel_evidence_id}>
                  <span
                    className="absolute -left-[26px] top-2 size-3 rounded-full bg-primary"
                    aria-hidden="true"
                  />
                  <h4 className="mb-2 text-base font-semibold">住宿</h4>
                  <p className="rounded-xl border border-border bg-bg p-4 text-sm">
                    {stay.hotel?.hotel_name ?? "住宿报价资料待更新"}
                  </p>
                </section>
              ))}
            </div>
          </section>
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
      {plan.hotel_stays?.map((stay) => (
        <details key={stay.hotel_evidence_id}>
          <summary>
            住宿报价 · {stay.check_in}—{stay.check_out}
          </summary>
          {!stay.hotel ||
          plan.needs_refresh.includes(stay.hotel_evidence_id) ||
          now >= Date.parse(stay.hotel.expires_at) ? (
            <p className="warning small">
              此住宿报价需更新，价格与可订状态请重新查询。
            </p>
          ) : null}
          {stay.hotel && <Hotel card={stay.hotel} />}
        </details>
      ))}
      {plan.draft_id && confirm && (
        <div className="confirm-bar">
          <Button
            className="primary"
            disabled={disabled || blocked || plan.status === "confirmed"}
            onClick={() => void confirm()}
          >
            确认保存此版本
          </Button>
        </div>
      )}
    </section>
  );
}

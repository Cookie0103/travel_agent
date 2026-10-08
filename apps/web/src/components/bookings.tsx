/** User confirmation and canonical booking recovery; unknown states only reconcile. */
"use client";
import type { Booking } from "@/lib/api";
import { SourceRef, useClock } from "./results";
import { errorExplanation } from "@/lib/error-explanation";
import { bookingCanConfirm, partyLabel } from "@/lib/availability";

const labels: Record<Booking["status"], string> = {
  quoted: "暂留结果待核对",
  held: "已暂留 · 等待你确认",
  confirmed: "已确认 · 等待供应商结果",
  booked: "模拟订单已创建",
  failed: "未完成预订",
  unknown: "结果不明 · 请先对账",
  expired: "暂留已过期",
};

export function Bookings({
  bookings,
  revision,
  disabled,
  hold,
  act,
}: {
  bookings: Booking[];
  revision?: number;
  disabled: boolean;
  hold: (id: string, revision: number) => Promise<void>;
  act: (id: string, action: "confirm" | "reconcile") => Promise<void>;
}) {
  const now = useClock();
  if (!bookings.length) return null;
  return (
    <section className="results-section">
      <div className="section-heading">
        <h2>模拟预订</h2>
        <span className="tag">无真实付款</span>
      </div>
      {bookings.map((booking) => {
        const stale = booking.offer.request.revision !== revision;
        return (
          <article className="hotel-card" key={booking.booking_id}>
            <h3>{booking.offer.hotel_name}</h3>
            <strong className={`status-chip status-${booking.status}`}>
              {labels[booking.status]}
            </strong>
            <p>
              ¥ {booking.total} {booking.offer.currency} ·{" "}
              {booking.offer.room_type}
            </p>
            <p>
              {booking.offer.request.start_date} —{" "}
              {booking.offer.request.end_date} ·{" "}
              {partyLabel(booking.offer.request)}
            </p>
            <p>
              {booking.offer.refundable ? "可退报价" : "不可退报价"} ·{" "}
              {booking.offer.breakfast ? "含早餐" : "不含早餐"}
            </p>
            <details>
              <summary>来源与版本</summary>
              <p className="muted small">
                报价条件版本 {booking.offer.request.revision} ·{" "}
                <SourceRef value={booking.source_ref} />
                <br />
                预订 {booking.booking_id}
              </p>
            </details>
            {booking.expires_at && (
              <p>
                暂留到期{" "}
                {new Date(booking.expires_at).toLocaleString("zh-CN", {
                  timeZone: "Asia/Tokyo",
                })}
              </p>
            )}
            {stale && (
              <p className="warning">
                此预订使用旧旅行条件；不会覆盖当前行程。
              </p>
            )}
            {booking.status === "held" && (
              <>
                <p>确认后将创建上述金额和入住条件的模拟订单，请先核对。</p>
                <button
                  className="primary"
                  disabled={
                    disabled || !bookingCanConfirm(booking, revision, now)
                  }
                  onClick={() => void act(booking.booking_id, "confirm")}
                >
                  确认模拟预订
                </button>
              </>
            )}
            {booking.status === "quoted" && (
              <button
                disabled={disabled || stale}
                onClick={() =>
                  void hold(
                    booking.offer.offer_id,
                    booking.offer.request.revision,
                  )
                }
              >
                核对并重试同一暂留
              </button>
            )}
            {["confirmed", "unknown"].includes(booking.status) && (
              <>
                <p className="warning">
                  供应商可能已创建订单。先核对状态，再决定下一步。
                </p>
                <button
                  disabled={disabled}
                  onClick={() => void act(booking.booking_id, "reconcile")}
                >
                  核对供应商状态
                </button>
              </>
            )}
            {booking.order_id && <p>模拟订单号 {booking.order_id}</p>}
            {booking.error_code && (
              <p className="warning">
                供应商状态：{errorExplanation(booking.error_code)}
              </p>
            )}
            {["failed", "expired"].includes(booking.status) && (
              <p>请重新比较酒店获取新报价。</p>
            )}
          </article>
        );
      })}
    </section>
  );
}

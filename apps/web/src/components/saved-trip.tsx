/** List this identity's confirmed trips, then read a selected canonical formal version. */
"use client";
import { Button } from "./ui/button";
import Link from "next/link";
import { useWorkspace } from "@/lib/use-workspace";
import { savedTripList } from "@/lib/saved-trips";
import { Banner } from "./banner";
import { PlanResults } from "./results";

function TripSkeleton() {
  return (
    <div className="trip-grid" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <div className="skeleton-card" key={i}>
          <span />
          <span />
          <span />
          <span />
        </div>
      ))}
    </div>
  );
}

export function SavedTrip() {
  const workspace = useWorkspace({ savedOnly: true });
  const list = savedTripList(workspace.trips, {
    identityPresent: !!workspace.identity,
    restoring: workspace.restoring,
    busy: workspace.busy,
    error: workspace.error || workspace.historyError,
    nextCursor: workspace.tripCursor,
  });
  const disabled = workspace.busy || workspace.restoring;
  return (
    <main className="page page-wide" id="main-content" tabIndex={-1}>
      <header className="page-header">
        <h1>我的行程</h1>
        <p className="notice info-callout">
          只读取当前演示身份已经确认的正式版本。刷新不会重新生成、修改行程或创建订单。
        </p>
      </header>
      {list.phase === "loading" && (
        <div role="status">
          <p className="muted small">正在读取已保存行程…</p>
          {!list.items.length && <TripSkeleton />}
        </div>
      )}
      {(workspace.error || workspace.historyError) && (
        <Banner kind="error">
          {workspace.error || workspace.historyError}
          {workspace.identity && (
            <Button
              variant="outline"
              disabled={disabled}
              onClick={() => void workspace.refresh()}
            >
              重新读取
            </Button>
          )}
        </Banner>
      )}
      {list.phase === "identity_missing" && (
        <div className="empty-state page-empty" role="status">
          <p>演示身份未保留，无法读取已保存行程。请返回对话。</p>
          <Link className="link-button" href="/">
            返回对话
          </Link>
        </div>
      )}
      {list.items.length > 0 && (
        <section className="trip-grid" aria-label="已确认旅行">
          {list.items.map((trip) => {
            const viewing = trip.plan_id === workspace.plan?.plan_id;
            const current = trip.session_id === workspace.identity?.session_id;
            return (
              <article
                className="trip-card"
                data-viewing={viewing || undefined}
                aria-current={viewing || undefined}
                key={trip.session_id}
              >
                <div className="trip-card-head">
                  <h2>{trip.city || "未设置目的地"}</h2>
                  <span
                    className="version-badge"
                    title={`第 ${trip.current_version} 版`}
                  >
                    V{trip.current_version}
                  </span>
                </div>
                <p className="trip-dates">
                  {trip.start_date
                    ? `${trip.start_date}${trip.end_date ? ` — ${trip.end_date}` : ""}`
                    : "日期未定"}
                </p>
                {current && <span className="count-chip">当前旅行</span>}
                <p className="muted small">锁定或修改都会生成新版本</p>
                <div className="trip-card-actions">
                  <Button
                    className="border-[var(--accent)] bg-[var(--accent)] text-white hover:bg-[var(--primary-strong,#6d3fd1)]"
                    disabled={disabled}
                    onClick={() => void workspace.switchTrip(trip.session_id)}
                  >
                    {viewing ? "正在查看" : "查看行程"}
                  </Button>
                </div>
              </article>
            );
          })}
        </section>
      )}
      {workspace.tripCursor && (
        <div className="group-more">
          <Button
            variant="outline"
            disabled={disabled}
            onClick={() => void workspace.loadMoreTrips()}
          >
            读取更早旅行
          </Button>
        </div>
      )}
      {list.phase === "more" && (
        <p className="muted">当前页没有已确认行程，可以继续读取更早旅行。</p>
      )}
      {list.phase === "ready" && !workspace.plan && (
        <p className="muted small">选择一份已确认行程查看。</p>
      )}
      {list.phase === "empty" && (
        <div className="empty-state page-empty">
          <p className="empty-title">当前身份还没有确认的行程</p>
          <p className="muted small">
            在对话中确认一份行程后，它会以正式版本出现在这里。
          </p>
          <Link className="link-button" href="/">
            去对话规划
          </Link>
        </div>
      )}
      {workspace.plan && (
        <section className="plan-detail" aria-label="行程详情">
          <PlanResults
            plan={workspace.plan}
            disabled={disabled}
            token={workspace.identity?.token}
          />
        </section>
      )}
      <p className="page-footer-link">
        <Link href="/">返回对话继续规划</Link>
      </p>
    </main>
  );
}

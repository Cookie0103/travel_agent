/** List this identity's confirmed trips, then read a selected canonical formal version. */
"use client";
import { Loading } from "./ui/loading";
import { Button } from "./ui/button";
import Link from "next/link";
import { useWorkspace } from "@/lib/use-workspace";
import { savedTripList } from "@/lib/saved-trips";
import { Banner } from "./banner";
import { PlanResults } from "./results";

export function SavedTrip() {
  const workspace = useWorkspace({ savedOnly: true });
  const list = savedTripList(workspace.trips, {
    identityPresent: !!workspace.identity,
    restoring: workspace.restoring,
    busy: workspace.busy,
    error: workspace.error || workspace.historyError,
    nextCursor: workspace.tripCursor,
  });
  return (
    <main className="page">
      <h1>我的行程</h1>
      <p className="notice">
        只读取当前演示身份已经确认的正式版本。刷新不会重新生成、修改行程或创建订单。
      </p>
      {list.phase === "loading" && <Loading>正在读取已保存行程…</Loading>}
      {(workspace.error || workspace.historyError) && (
        <Banner kind="error">
          {workspace.error || workspace.historyError}
          {workspace.identity && (
            <Button
              variant="outline"
              disabled={workspace.busy || workspace.restoring}
              onClick={() => void workspace.refresh()}
            >
              重新读取
            </Button>
          )}
        </Banner>
      )}
      {list.phase === "identity_missing" && (
        <p role="status">演示身份未保留，无法读取已保存行程。请返回对话。</p>
      )}
      {list.items.length > 0 && (
        <section aria-label="已确认旅行">
          {list.items.map((trip) => (
            <section className="plan-summary" key={trip.session_id}>
              <div>
                <strong>
                  {trip.city || "未设置目的地"} · V{trip.current_version}
                </strong>
                {trip.start_date && (
                  <p>
                    {trip.start_date}
                    {trip.end_date ? `—${trip.end_date}` : ""}
                  </p>
                )}
                {trip.session_id === workspace.identity?.session_id && (
                  <span className="small muted">当前旅行</span>
                )}
              </div>
              <Button
                variant="outline"
                disabled={workspace.busy || workspace.restoring}
                onClick={() => void workspace.switchTrip(trip.session_id)}
              >
                查看行程
              </Button>
            </section>
          ))}
        </section>
      )}
      {workspace.tripCursor && (
        <Button
          variant="outline"
          disabled={workspace.busy || workspace.restoring}
          onClick={() => void workspace.loadMoreTrips()}
        >
          读取更早旅行
        </Button>
      )}
      {list.phase === "more" && (
        <p>当前页没有已确认行程，可以继续读取更早旅行。</p>
      )}
      {list.phase === "ready" && !workspace.plan && (
        <p>选择一份已确认行程查看。</p>
      )}
      {list.phase === "empty" && (
        <div className="empty-state">
          <p>当前身份还没有确认的行程</p>
        </div>
      )}
      {workspace.plan && (
        <PlanResults
          plan={workspace.plan}
          disabled={workspace.busy || workspace.restoring}
          token={workspace.identity?.token}
        />
      )}
      <p>
        <Link href="/">返回对话继续规划</Link>
      </p>
    </main>
  );
}

/** Right-hand trip panel: conditions summary, plan, bookings, confirm action and preferences. */
"use client";
import { useState } from "react";
import type { Workspace } from "./workbench";
import { Conditions } from "./conditions";
import { PlanResults } from "./results";
import { Bookings } from "./bookings";
import { PreferencePanel } from "./preferences";
import { partyLabel } from "@/lib/availability";

const transportLabels: Record<string, string> = {
  walk: "步行",
  transit: "公共交通",
  taxi: "出租车",
};

export function TripPanel({
  workspace,
  className,
  close,
}: {
  workspace: Workspace;
  className: string;
  close: () => void;
}) {
  const { request, identity, plan } = workspace;
  const [editing, setEditing] = useState(false);
  if (!identity) return null;
  return (
    <aside className={className} aria-label="本次行程">
      <div className="panel-head">
        <h2>本次行程</h2>
        <button aria-label="收起本次行程" onClick={close}>
          ×
        </button>
      </div>
      {request && (
        <section className="panel-block">
          <div className="section-heading">
            <h3>旅行条件</h3>
            <button onClick={() => setEditing((value) => !value)}>
              {editing ? "收起" : "编辑"}
            </button>
          </div>
          <p>
            {request.city} · {request.start_date}—{request.end_date}
          </p>
          <p>
            {partyLabel(request)} · {request.rooms} 间 · ¥{request.budget}
          </p>
          <p>
            {transportLabels[request.transport ?? ""] ?? request.transport} ·{" "}
            {request.departure_time} 出发
          </p>
          <p className="small muted">也可以直接在对话里告诉我。</p>
          {editing && (
            <Conditions
              key={request.revision}
              request={request}
              disabled={workspace.busy}
              save={workspace.saveConditions}
            />
          )}
        </section>
      )}
      {plan ? (
        <PlanResults
          plan={plan}
          disabled={workspace.busy}
          confirm={workspace.confirm}
          lock={workspace.lock}
        />
      ) : (
        <section className="panel-block">
          <h3>行程</h3>
          <p className="muted">还没有行程草稿；在对话里让我生成。</p>
        </section>
      )}
      <Bookings
        bookings={workspace.bookings}
        revision={request?.revision}
        disabled={workspace.busy}
        hold={workspace.holdOffer}
        act={workspace.bookingAction}
      />
      <details className="panel-block">
        <summary>长期偏好</summary>
        <PreferencePanel
          key={identity.user_id}
          identity={identity}
          onError={workspace.fail}
        />
      </details>
    </aside>
  );
}

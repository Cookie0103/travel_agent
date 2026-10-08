/** Right-hand trip panel: conditions summary, plan, bookings, confirm action and preferences. */
"use client";
import { useState } from "react";
import type { Workspace } from "./workbench";
import { Conditions } from "./conditions";
import { formatYen, PlanResults } from "./results";
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
            {!editing && <h3>旅行条件</h3>}
            <button onClick={() => setEditing((value) => !value)}>
              {editing ? "收起" : "编辑"}
            </button>
          </div>
          {!editing && (
            <>
              {request.city || request.start_date || request.adults ? (
                <>
                  <p>
                    {[
                      request.city,
                      request.start_date &&
                        `${request.start_date}—${request.end_date || "待定"}`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                  <p>
                    {[
                      request.adults
                        ? partyLabel(request)
                        : request.rooms && `${request.rooms} 间房`,
                      request.budget && `¥${formatYen(request.budget)}`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                  <p>
                    {[
                      transportLabels[request.transport ?? ""],
                      request.departure_time &&
                        `${request.departure_time.slice(0, 5)} 出发`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </>
              ) : (
                <p className="muted">还没有设定条件，直接在对话里告诉我</p>
              )}
            </>
          )}
          {editing && (
            <Conditions
              key={request.revision}
              request={request}
              disabled={workspace.busy}
              save={async (fields) => {
                const saved = await workspace.saveConditions(fields);
                if (saved) setEditing(false);
                return saved;
              }}
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
          token={identity.token}
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

/** Right-hand trip panel: conditions summary, plan, bookings, confirm action and preferences. */
"use client";
import { useState } from "react";
import type { Workspace } from "./workbench";
import { Conditions } from "./conditions";
import { PlanResults } from "./results";
import { Bookings } from "./bookings";
import { PreferencePanel } from "./preferences";
import { moneyLabel, moneyRangeLabel, partyLabel } from "@/lib/availability";
import { sourceRows } from "@/lib/condition-source";
import { currentPace, paceLine } from "@/lib/pace";
import { useLongTermPace } from "@/lib/use-long-term-pace";

const transportLabels: Record<string, string> = {
  walk: "步行",
  transit: "公共交通",
  taxi: "出租车",
};

export function TripPanel({
  workspace,
  id,
  labelledBy,
  className,
  close,
}: {
  workspace: Workspace;
  id?: string;
  labelledBy?: string;
  className: string;
  close: () => void;
}) {
  const { request, identity, plan } = workspace;
  const [editing, setEditing] = useState(false);
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const pace = currentPace(
    request?.soft_constraints ?? [],
    request?.hard_constraints ?? [],
  );
  const longTerm = useLongTermPace(
    identity,
    `${workspace.run?.run_id ?? ""}:${workspace.run?.status ?? ""}`,
  );
  if (!identity) return null;
  const party =
    request && (request.adults || request.child_ages != null)
      ? partyLabel(request)
      : request?.rooms
        ? `${request.rooms} 间房`
        : "";
  return (
    <aside
      id={id}
      className={className}
      role="tabpanel"
      aria-labelledby={labelledBy}
      aria-label="本次行程"
    >
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
          {!editing &&
            (request.city ||
            request.hotel_search_location ||
            request.start_date ||
            request.end_date ||
            request.adults ||
            request.rooms ||
            request.child_ages != null ||
            request.budget ||
            request.lodging_budget ||
            request.lodging_budget_unlimited ||
            request.transport ||
            request.departure_time ||
            pace ? (
              <>
                {(request.city || request.start_date || request.end_date) && (
                  <p className="cond-title">
                    {[
                      request.city,
                      (request.start_date || request.end_date) &&
                        `${request.start_date || "开始待定"}—${request.end_date || "结束待定"}`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                )}
                <ul className="cond-chips" aria-label="其他条件">
                  {party && <li className="is-set">{party}</li>}
                  {request.budget && (
                    <li>
                      全程预算 {moneyLabel(request.budget, request.currency)}
                    </li>
                  )}
                  {(request.transport || request.departure_time) && (
                    <li>
                      {[
                        transportLabels[request.transport ?? ""],
                        request.departure_time &&
                          `${request.departure_time.slice(0, 5)} 出发`,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </li>
                  )}
                  <li className={pace || longTerm ? undefined : "is-muted"}>
                    {paceLine(pace, longTerm)}
                  </li>
                  {request.hotel_search_location && (
                    <li>住宿查询地点：{request.hotel_search_location}</li>
                  )}
                  {request.lodging_budget_unlimited && <li>每晚预算：不限</li>}
                  {request.lodging_budget && (
                    <li>
                      住宿预算：
                      {moneyRangeLabel(
                        request.lodging_budget.amount.lower,
                        request.lodging_budget.amount.upper,
                        request.lodging_budget.currency,
                        { lower: "下限未填", upper: "上限未填" },
                      )}{" "}
                      ·{" "}
                      {request.lodging_budget.basis === "per_room_night"
                        ? "每房每晚"
                        : "住宿总额"}
                    </li>
                  )}
                </ul>
              </>
            ) : (
              <p className="muted">还没有设定条件，直接在对话里告诉我</p>
            ))}
          {!editing && request.segments?.length && (
            <ul className="cond-segments small" aria-label="城市段">
              {request.segments.map((segment) => (
                <li key={segment.arrive}>
                  {segment.city} · {segment.arrive}—{segment.depart}
                  {segment.hotel_search_location &&
                    ` · 住宿地点：${segment.hotel_search_location}`}
                </li>
              ))}
            </ul>
          )}
          {request.lodging_budget_unlimited ? null : request.budget_relation ? (
            <p
              className={
                request.budget_relation.status === "conflict"
                  ? "error small"
                  : "muted small"
              }
            >
              {request.budget_relation.message}
            </p>
          ) : (
            <p className="muted small">服务版本暂不支持住宿预算关系校验。</p>
          )}
          {!editing && sourceRows(request.field_sources).length > 0 && (
            <details className="fold-muted">
              <summary>来源</summary>
              <p className="small muted">
                {sourceRows(request.field_sources).join("；")}
              </p>
            </details>
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
      {workspace.confirmation?.session_id === identity.session_id && (
        <section className="panel-block" role="status">
          <h3>已确认保存 · V{workspace.confirmation.version}</h3>
          <p>正在读取正式行程；读取失败可重试，无需再次保存。</p>
          <button
            disabled={workspace.busy || workspace.restoring}
            onClick={() => void workspace.refresh()}
          >
            重新读取已保存行程
          </button>
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
        !workspace.confirmation && (
          <section className="panel-block">
            <h3>行程</h3>
            <p className="muted">还没有行程草稿；在对话里让我生成。</p>
          </section>
        )
      )}
      <Bookings
        bookings={workspace.bookings}
        revision={request?.revision}
        disabled={workspace.busy}
        hold={workspace.holdOffer}
        act={workspace.bookingAction}
      />
      <details
        className="panel-block"
        onToggle={(event) => setPreferencesOpen(event.currentTarget.open)}
      >
        <summary>长期偏好</summary>
        <PreferencePanel
          key={identity.session_id}
          active={preferencesOpen}
          identity={identity}
          refreshKey={`${workspace.run?.run_id ?? ""}:${workspace.run?.status ?? ""}`}
          onError={workspace.fail}
          onChanged={() => void workspace.refresh()}
        />
      </details>
    </aside>
  );
}

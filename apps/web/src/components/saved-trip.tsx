/** Read the current user's confirmed plan using the existing recovery hook and canonical cards. */
"use client";
import Link from "next/link";
import { useWorkspace } from "@/lib/use-workspace";
import { PlanResults } from "./results";

export function SavedTrip() {
  const workspace = useWorkspace({ savedOnly: true });
  return (
    <main>
      <p className="eyebrow">KYOTO / SAVED TRIP</p>
      <h1>已保存行程</h1>
      <p className="notice">
        只读取当前演示身份已经确认的正式版本。刷新不会重新生成、修改行程或创建订单。
      </p>
      {workspace.restoring && <p role="status">正在读取已保存行程…</p>}
      {workspace.error && (
        <div className="error-box" role="alert">
          {workspace.error}
          {workspace.identity && (
            <button
              disabled={workspace.busy}
              onClick={() => void workspace.refresh()}
            >
              重新读取
            </button>
          )}
        </div>
      )}
      {!workspace.restoring &&
        !workspace.error &&
        (!workspace.identity || !workspace.plan) && (
          <p>当前会话还没有已确认行程，请到工作台创建或确认方案。</p>
        )}
      {workspace.plan && (
        <PlanResults plan={workspace.plan} disabled={workspace.busy} />
      )}
      <p>
        <Link href="/">返回工作台继续规划</Link>
      </p>
    </main>
  );
}

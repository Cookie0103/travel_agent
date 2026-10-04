/** Read the current user's confirmed plan using the existing recovery hook and canonical cards. */
"use client";
import Link from "next/link";
import { useWorkspace } from "@/lib/use-workspace";
import { Banner } from "./banner";
import { PlanResults } from "./results";

export function SavedTrip() {
  const workspace = useWorkspace({ savedOnly: true });
  const empty =
    !workspace.restoring &&
    !workspace.error &&
    (!workspace.identity || !workspace.plan);
  return (
    <main className="page">
      <h1>我的行程</h1>
      <p className="notice">
        只读取当前演示身份已经确认的正式版本。刷新不会重新生成、修改行程或创建订单。
      </p>
      {workspace.restoring && <p role="status">正在读取已保存行程…</p>}
      {workspace.error && (
        <Banner kind="error">
          {workspace.error}
          {workspace.identity && (
            <button
              disabled={workspace.busy}
              onClick={() => void workspace.refresh()}
            >
              重新读取
            </button>
          )}
        </Banner>
      )}
      {empty && (
        <div className="empty-state">
          <p>还没有确认的行程</p>
          <Link href="/" className="button-link">
            去对话
          </Link>
        </div>
      )}
      {workspace.plan && (
        <PlanResults plan={workspace.plan} disabled={workspace.busy} />
      )}
      {!empty && (
        <p>
          <Link href="/">返回对话继续规划</Link>
        </p>
      )}
    </main>
  );
}

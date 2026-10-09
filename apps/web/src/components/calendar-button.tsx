"use client";
import { useState } from "react";

export function CalendarButton({
  planId,
  token,
  disabled,
}: {
  planId: string;
  token: string;
  disabled: boolean;
}) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function download() {
    setLoading(true);
    setError("");
    let url: string | undefined;
    try {
      const response = await fetch(`/api/plans/${planId}/calendar.ics`, {
        cache: "no-store",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok)
        throw new Error("日历下载失败，请检查会话并重新读取行程。");
      url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "trip.ics";
      link.click();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "日历下载失败");
    } finally {
      if (url) URL.revokeObjectURL(url);
      setLoading(false);
    }
  }
  return (
    <div>
      <button disabled={disabled || loading} onClick={() => void download()}>
        导出到日历 (.ics)
      </button>
      <p className="small muted">下载后在 Google Calendar →设置→导入</p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </div>
  );
}

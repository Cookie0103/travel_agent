"use client";
import { Button } from "./ui/button";
import { useState } from "react";
import { icsFilename } from "../lib/calendar-file";

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
      const blobUrl = URL.createObjectURL(await response.blob());
      url = blobUrl;
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = icsFilename(response.headers.get("Content-Disposition"));
      document.body.appendChild(link);
      link.click();
      link.remove();
      // 下载由浏览器异步读取该地址，立即释放可能得到空文件；延后释放。
      setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
      url = undefined;
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "日历下载失败");
    } finally {
      if (url) URL.revokeObjectURL(url);
      setLoading(false);
    }
  }
  return (
    <div className="calendar-export">
      <Button
        variant="outline"
        disabled={disabled || loading}
        onClick={() => void download()}
      >
        导出到日历 (.ics)
      </Button>
      <p className="small muted">下载后在 Google Calendar →设置→导入</p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </div>
  );
}

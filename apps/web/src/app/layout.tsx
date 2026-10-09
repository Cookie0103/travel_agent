/** Workbench shell; the browser receives application data, never supplier keys. */
import type { Metadata } from "next";
import { SiteNav } from "@/components/site-nav";
import "./globals.css";
export const metadata: Metadata = {
  title: "旅程助手",
  description: "对话式旅行规划助手：比较、校验、保留修改",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <SiteNav />
        {children}
      </body>
    </html>
  );
}

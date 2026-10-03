/** Workbench shell; the browser receives application data, never supplier keys. */
import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "京都旅行工作台",
  description: "可核验的旅行规划演示",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

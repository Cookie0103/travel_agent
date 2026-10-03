/** Workbench shell; the browser receives application data, never supplier keys. */
import type { Metadata } from "next";
import Link from "next/link";
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
      <body>
        <nav className="site-nav" aria-label="页面导航">
          <Link href="/articles">京都攻略</Link>
          <Link href="/">规划工作台</Link>
          <Link href="/plans">已保存行程</Link>
        </nav>
        {children}
      </body>
    </html>
  );
}

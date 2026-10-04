/** Workbench shell; the browser receives application data, never supplier keys. */
import type { Metadata } from "next";
import { Inter, Noto_Sans_SC } from "next/font/google";
import { SiteNav } from "@/components/site-nav";
import "./globals.css";
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});
const chinese = Noto_Sans_SC({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-chinese",
  display: "swap",
});
export const metadata: Metadata = {
  title: "旅程助手",
  description: "对话式旅行规划助手：比较、校验、保留修改",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" className={`${inter.variable} ${chinese.variable}`}>
      <body>
        <SiteNav />
        {children}
      </body>
    </html>
  );
}

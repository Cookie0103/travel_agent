/** Top bar: brand and the two user-facing destinations; guides are reached from source links. */
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "对话" },
  { href: "/plans", label: "我的行程" },
];

export function SiteNav() {
  const pathname = usePathname();
  return (
    <nav className="site-nav" aria-label="页面导航">
      <Link href="/" className="brand">
        <span aria-hidden="true">◆</span> 旅程助手
      </Link>
      {links.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          aria-current={pathname === link.href ? "page" : undefined}
        >
          {link.label}
        </Link>
      ))}
    </nav>
  );
}

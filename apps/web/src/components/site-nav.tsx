/** Top bar: brand and the user-facing destinations. */
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { navLinks, isCurrentNav } from "@/lib/nav-links";

export function SiteNav() {
  const pathname = usePathname();
  return (
    <nav className="site-nav" aria-label="页面导航">
      <Link href="/" className="brand">
        <span aria-hidden="true">◆</span> 旅程助手
      </Link>
      {navLinks.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          aria-current={isCurrentNav(link.href, pathname) ? "page" : undefined}
        >
          {link.label}
        </Link>
      ))}
    </nav>
  );
}

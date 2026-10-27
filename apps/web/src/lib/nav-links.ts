/** Top-bar destinations; the current page is matched by path prefix so article details keep 攻略 active. */
export const navLinks = [
  { href: "/", label: "对话" },
  { href: "/plans", label: "我的行程" },
  { href: "/articles", label: "攻略与来源" },
];

export const isCurrentNav = (href: string, pathname: string | null) =>
  href === "/"
    ? pathname === "/"
    : pathname === href || !!pathname?.startsWith(`${href}/`);

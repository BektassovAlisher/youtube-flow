"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { logout } from "./login/actions";

const NAV = [
  { href: "/", label: "Создать" },
  { href: "/library", label: "Библиотека" },
];

function toggleTheme() {
  // the pre-paint script in layout.tsx already set data-theme on <html>
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  const apply = () => {
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {}
  };
  // a short cross-fade, so the page changes colour instead of flashing
  if (!document.startViewTransition || matchMedia("(prefers-reduced-motion: reduce)").matches) return apply();
  document.startViewTransition(apply);
}

export default function Header({ auth }: { auth: "off" | "in" | "out" }) {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href) || (href === "/library" && path.startsWith("/videos")));

  return (
    <header className="header">
      <div className="wrap navbar">
        <Link href="/" className="brand">
          VideoFlow
        </Link>
        <nav className="nav" aria-label="Разделы">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="header-end">
          {auth === "out" && (
            <Link href={`/login?next=${encodeURIComponent(path)}`} className="signin" aria-label="Войти" title="Войти">
              <span className="signin-text">Войти</span>
              <svg className="signin-icon" viewBox="0 0 24 24" aria-hidden>
                <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3" />
              </svg>
            </Link>
          )}
          {auth === "in" && (
            <form action={logout}>
              <button className="signin" aria-label="Выйти" title="Выйти">
                <span className="signin-text">Выйти</span>
                <svg className="signin-icon" viewBox="0 0 24 24" aria-hidden>
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
                </svg>
              </button>
            </form>
          )}
          <button className="theme-toggle" onClick={toggleTheme} aria-label="Сменить тему" title="Сменить тему">
            <svg className="moon" viewBox="0 0 24 24" aria-hidden>
              <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
            </svg>
            <svg className="sun" viewBox="0 0 24 24" aria-hidden>
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
            </svg>
          </button>
        </div>
      </div>
    </header>
  );
}

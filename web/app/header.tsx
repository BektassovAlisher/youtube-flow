"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { flushSync } from "react-dom";

const NAV = [
  { href: "/", label: "Создать" },
  { href: "/library", label: "Библиотека" },
];

type Theme = "dark" | "light";

export default function Header() {
  const path = usePathname();
  const [scrolled, setScrolled] = useState(false);
  const [theme, setTheme] = useState<Theme | null>(null); // the pre-paint script in layout.tsx already set it on <html>

  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  }, []);

  // nav turns into a bordered pill once the page is scrolled
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  function toggleTheme(e: React.MouseEvent) {
    const next: Theme = theme === "light" ? "dark" : "light";
    const apply = () => {
      document.documentElement.dataset.theme = next;
      try {
        localStorage.setItem("theme", next);
      } catch {}
      flushSync(() => setTheme(next));
    };
    if (!document.startViewTransition || matchMedia("(prefers-reduced-motion: reduce)").matches) return apply();

    // the new theme grows as a circle out of the click point, like on the reference site
    const { clientX: x, clientY: y } = e;
    const r = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    document
      .startViewTransition(apply)
      .ready.then(() => {
        document.documentElement.animate(
          { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${r}px at ${x}px ${y}px)`] },
          { duration: 650, easing: "cubic-bezier(0.2, 0.7, 0.2, 1)", pseudoElement: "::view-transition-new(root)" },
        );
      })
      .catch(() => {}); // transition skipped (e.g. double click, hidden tab): the theme is already applied, only the animation is lost
  }

  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href) || (href === "/library" && path.startsWith("/videos")));

  return (
    <header className="header" data-scrolled={scrolled || undefined}>
      <div className="header-wrap">
        <div className="navbar">
          <Link href="/" className="brand">
            <span className="dot" aria-hidden />
            VideoFlow
          </Link>
          <nav className="nav">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined}>
                {n.label}
              </Link>
            ))}
          </nav>
          <button className="theme-toggle" onClick={toggleTheme} aria-label={theme === "light" ? "Тёмная тема" : "Светлая тема"} title="Сменить тему">
            {theme && (
              <svg key={theme} viewBox="0 0 24 24" aria-hidden>
                {theme === "light" ? (
                  <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
                ) : (
                  <>
                    <circle cx="12" cy="12" r="4" />
                    <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
                  </>
                )}
              </svg>
            )}
          </button>
        </div>
      </div>
    </header>
  );
}

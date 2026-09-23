import type { Metadata } from "next";
import { Bricolage_Grotesque, Inter, Inter_Tight, JetBrains_Mono } from "next/font/google";
import type { CSSProperties } from "react";
import Header from "./header";
import "./globals.css";

// Same families as the reference; Inter Tight covers the Cyrillic that Bricolage lacks
const display = Bricolage_Grotesque({ subsets: ["latin"], axes: ["opsz"], variable: "--font-display" });
const displayCyr = Inter_Tight({ subsets: ["cyrillic"], variable: "--font-display-cyr" });
const sans = Inter({ subsets: ["latin", "cyrillic"], variable: "--font-sans" });
const mono = JetBrains_Mono({ subsets: ["latin", "cyrillic"], weight: ["400", "500", "600"], variable: "--font-mono" });

// Bricolage's own face only, then Inter Tight. next/font's Arial stand-in for Bricolage has no unicode-range,
// so leaving it in the stack would catch Cyrillic before Inter Tight (and Turbopack ignores adjustFontFallback: false).
const displayStack = `${display.style.fontFamily.split(",")[0]}, ${displayCyr.style.fontFamily}, sans-serif`;

// runs before first paint so the page never flashes the wrong theme: saved choice, else the OS preference
const THEME_SCRIPT = `try{document.documentElement.dataset.theme=localStorage.getItem("theme")||(matchMedia("(prefers-color-scheme: light)").matches?"light":"dark")}catch(e){}`;

export const metadata: Metadata = {
  title: "VideoFlow",
  description: "Конспекты, сценарии и подкасты из обучающих видео на YouTube",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="ru"
      className={`${display.variable} ${displayCyr.variable} ${sans.variable} ${mono.variable}`}
      style={{ "--display": displayStack } as CSSProperties}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <div className="backdrop" aria-hidden>
          <div className="glow a" />
          <div className="glow b" />
        </div>
        <Header />
        <main className="wrap page">{children}</main>
      </body>
    </html>
  );
}

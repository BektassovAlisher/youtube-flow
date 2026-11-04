import type { Metadata } from "next";
import { Golos_Text, Literata } from "next/font/google";
import { cookies } from "next/headers";
import { authRequired, SESSION_COOKIE, validSession } from "@/lib/session";
import Header from "./header";
import "./globals.css";

// Reasons for both faces are in DESIGN.md: Literata is made for long reading and carries the material itself,
// Golos Text was made for Russian-language interfaces and carries the app around it.
const serif = Literata({ subsets: ["latin", "cyrillic"], style: ["normal", "italic"], axes: ["opsz"], variable: "--font-serif" });
const sans = Golos_Text({ subsets: ["latin", "cyrillic"], variable: "--font-sans" });

// runs before first paint so the page never flashes the wrong theme: saved choice, else the OS preference
const THEME_SCRIPT = `try{document.documentElement.dataset.theme=localStorage.getItem("theme")||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light")}catch(e){}`;

export const metadata: Metadata = {
  title: "VideoFlow",
  description: "Конспекты, вопросы для самопроверки и подкасты из обучающих видео, подкастов, статей и документов",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // "off": no APP_PASSWORD, nothing to sign in to
  const auth = !authRequired() ? "off" : validSession((await cookies()).get(SESSION_COOKIE)?.value) ? "in" : "out";
  return (
    <html lang="ru" className={`${serif.variable} ${sans.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <Header auth={auth} />
        <main className="wrap page">{children}</main>
        <footer className="footer">
          <div className="wrap">
            <p>Конспекты, ответы и сценарии пишет языковая модель по тексту материала. Важное сверяйте с оригиналом по таймкодам и номерам абзацев.</p>
          </div>
        </footer>
      </body>
    </html>
  );
}

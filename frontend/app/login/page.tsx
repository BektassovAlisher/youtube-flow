import Link from "next/link";
import { authRequired, safeNext } from "@/lib/session";
import { login } from "./actions";

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams;
  const next = safeNext(typeof params.next === "string" ? params.next : "/");

  if (!authRequired()) {
    return (
      <div className="notice fade">
        <h3>Вход не нужен</h3>
        <p>Пароль приложения не задан (APP_PASSWORD), всё доступно без входа.</p>
        <p>
          <Link href={next}>Вернуться →</Link>
        </p>
      </div>
    );
  }

  return (
    <form action={login} className="login box rise">
      <h1 className="section-title">Вход</h1>
      <p>Смотреть конспекты можно без входа. Пароль нужен, чтобы обрабатывать новые видео, задавать вопросы, создавать аудио и удалять.</p>
      <input type="hidden" name="next" value={next} />
      <input className="field" type="password" name="password" placeholder="Пароль" aria-label="Пароль" autoFocus required />
      <button className="btn primary">Войти</button>
      {params.error && <p className="error">Неверный пароль.</p>}
    </form>
  );
}

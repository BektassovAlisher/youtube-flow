import Link from "next/link";
import { authRequired, safeNext } from "@/lib/session";
import { login } from "./actions";

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams;
  const next = safeNext(typeof params.next === "string" ? params.next : "/");

  if (!authRequired()) {
    return (
      <div className="notice">
        <h3>Вход не нужен</h3>
        <p>Пароль приложения не задан (APP_PASSWORD), всё доступно без входа.</p>
        <p>
          <Link href={next}>Вернуться</Link>
        </p>
      </div>
    );
  }

  return (
    <form action={login} className="login">
      <h1>Вход</h1>
      <p>Смотреть конспекты можно без входа. Пароль нужен, чтобы обрабатывать новые материалы, задавать вопросы, создавать аудио и удалять.</p>
      <input type="hidden" name="next" value={next} />
      <div>
        <label className="field-label" htmlFor="password">Пароль</label>
        <input className="field" id="password" type="password" name="password" autoComplete="current-password" autoFocus required />
      </div>
      <button className="btn primary">Войти</button>
      {params.error && <p className="error" role="alert">Неверный пароль.</p>}
    </form>
  );
}
